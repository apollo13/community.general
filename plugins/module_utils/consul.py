# -*- coding: utf-8 -*-

# Copyright (c) 2022, Håkon Lerring
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import copy
import json

from ansible.module_utils.six.moves.urllib import error as urllib_error
from ansible.module_utils.six.moves.urllib.parse import urlencode
from ansible.module_utils.urls import open_url


def get_consul_url(configuration):
    return "%s://%s:%s/v1" % (
        configuration.scheme,
        configuration.host,
        configuration.port,
    )


def get_auth_headers(configuration):
    if configuration.token is None:
        return {}
    else:
        return {"X-Consul-Token": configuration.token}


class RequestError(Exception):
    def __init__(self, status, response_data=None):
        self.status = status
        self.response_data = response_data

    def __str__(self):
        if self.response_data is None:
            # self.status is already the message (backwards compat)
            return self.status
        return "HTTP %d: %s" % (self.status, self.response_data)


def handle_consul_response_error(response):
    if 400 <= response.status_code < 600:
        raise RequestError("%d %s" % (response.status_code, response.content))


def auth_argument_spec():
    return dict(
        host=dict(default="localhost"),
        port=dict(type="int", default=8500),
        scheme=dict(default="http"),
        validate_certs=dict(type="bool", default=True),
        token=dict(no_log=True),
        ca_path=dict(),
    )


def camel_case_key(key):
    parts = []
    for part in key.split("_"):
        if part in {"id", "ttl", "jwks", "jwt", "oidc", "iam", "sts"}:
            parts.append(part.upper())
        else:
            parts.append(part.capitalize())
    return "".join(parts)


STATE_PARAMETER = "state"
STATE_PRESENT = "present"
STATE_ABSENT = "absent"

OPERATION_READ = object()
OPERATION_CREATE = object()
OPERATION_UPDATE = object()
OPERATION_DELETE = object()


class _ConsulModule:
    """Base class for Consul modules.

    This class is considered private, till the API is fully fleshed out.
    As such backwards incompatible changes can occur even in bugfix releases.
    """

    api_endpoint = None  # type: str
    unique_identifier = None  # type: str
    result_key = None  # type: str
    create_only_fields = set()
    camel_case_fields = set()

    def __init__(self, module):
        self.module = module
        self.param_obj_mapping = {
            k: camel_case_key(k)
            for k in self.module.params
            if k not in STATE_PARAMETER and k not in auth_argument_spec()
        }

    def execute(self):
        module = self.module

        obj = self.read_object()

        changed = False
        diff = {}
        if module.params[STATE_PARAMETER] == STATE_PRESENT:
            obj_from_module = self.module_to_obj(obj is not None)
            if obj is None:
                new_obj = self.create_object(obj_from_module)
                diff = {"before": {}, "after": new_obj}
                changed = True
            else:
                if self._needs_update(obj, obj_from_module):
                    new_obj = self.update_object(obj, obj_from_module)
                    diff = {"before": obj, "after": new_obj}
                    changed = True
                else:
                    new_obj = obj
        elif module.params[STATE_PARAMETER] == STATE_ABSENT:
            if obj is not None:
                self.delete_object(obj)
                changed = True
                diff = {"before": obj, "after": {}}
            else:
                diff = {"before": {}, "after": {}}
            new_obj = None
        else:
            raise RuntimeError("Unknown state supplied.")

        result = {"changed": changed}
        if self.module._diff and changed:
            result["diff"] = diff
        if self.result_key:
            result[self.result_key] = new_obj
        module.exit_json(**result)

    def module_to_obj(self, is_update):
        obj = {}
        for k, v in self.module.params.items():
            result = self.map_param(k, v, is_update)
            if result:
                obj[result[0]] = result[1]
        return obj

    def map_param(self, k, v, is_update):
        def helper(item):
            return {camel_case_key(k): v for k, v in item.items()}

        if k in self.param_obj_mapping and v is not None:
            if isinstance(v, dict) and k in self.camel_case_fields:
                v = helper(v)
            elif isinstance(v, (list, tuple)) and k in self.camel_case_fields:
                v = [helper(i) for i in v]
            if is_update and k in self.create_only_fields:
                return
            return self.param_obj_mapping[k], v

    def _needs_update(self, api_obj, module_obj):
        api_obj = copy.deepcopy(api_obj)
        module_obj = copy.deepcopy(module_obj)
        return self.needs_update(api_obj, module_obj)

    def needs_update(self, api_obj, module_obj):
        for k, v in module_obj.items():
            if k not in api_obj:
                return True
            if api_obj[k] != v:
                return True
        return False

    def prepare_object(self, existing, obj):
        operational_attributes = {"CreateIndex", "CreateTime", "Hash", "ModifyIndex"}
        existing = {
            k: v for k, v in existing.items() if k not in operational_attributes
        }
        for k, v in obj.items():
            existing[k] = v
        return existing

    def endpoint_url(self, operation, identifier=None):
        if operation == OPERATION_CREATE:
            return self.api_endpoint
        else:
            assert identifier is not None
            return "/".join([self.api_endpoint, identifier])

    def read_object(self):
        url = self.endpoint_url(
            OPERATION_READ, self.module.params.get(self.unique_identifier)
        )
        try:
            return self.get(url)
        except RequestError as e:
            if e.status == 404:
                return
            elif e.status == 403 and b"ACL not found" in e.response_data:
                return
            raise

    def create_object(self, obj):
        if self.module.check_mode:
            return obj
        else:
            return self.put(self.api_endpoint, data=self.prepare_object({}, obj))

    def update_object(self, existing, obj):
        url = self.endpoint_url(
            OPERATION_UPDATE, existing.get(camel_case_key(self.unique_identifier))
        )
        if self.module.check_mode:
            return obj
        else:
            return self.put(url, data=self.prepare_object(existing, obj))

    def delete_object(self, obj):
        if self.module.check_mode:
            return {}
        else:
            url = self.endpoint_url(
                OPERATION_DELETE, obj.get(camel_case_key(self.unique_identifier))
            )
            return self.delete(url)

    def _request(self, method, url_parts, data=None, params=None):
        module_params = self.module.params

        if isinstance(url_parts, str):
            url_parts = [url_parts]
        if params:
            # Remove values that are None
            params = {k: v for k, v in params.items() if v is not None}

        ca_path = module_params.get("ca_path")
        base_url = "%s://%s:%s/v1" % (
            module_params["scheme"],
            module_params["host"],
            module_params["port"],
        )
        url = "/".join([base_url] + list(url_parts))

        headers = {}
        token = self.module.params.get("token")
        if token:
            headers["X-Consul-Token"] = token

        try:
            if data:
                data = json.dumps(data)
                headers["Content-Type"] = "application/json"
            if params:
                url = "%s?%s" % (url, urlencode(params))
            response = open_url(
                url,
                method=method,
                data=data,
                headers=headers,
                validate_certs=module_params["validate_certs"],
                ca_path=ca_path,
            )
            response_data = response.read()
            status = (
                response.status if hasattr(response, "status") else response.getcode()
            )

        except urllib_error.URLError as e:
            if isinstance(e, urllib_error.HTTPError):
                status = e.code
                response_data = e.fp.read()
            else:
                self.module.fail_json(
                    msg="Could not connect to consul agent at %s:%s, error was %s"
                    % (module_params["host"], module_params["port"], str(e))
                )
                raise

        if 400 <= status < 600:
            raise RequestError(status, response_data)

        return json.loads(response_data)

    def get(self, url_parts, **kwargs):
        return self._request("GET", url_parts, **kwargs)

    def put(self, url_parts, **kwargs):
        return self._request("PUT", url_parts, **kwargs)

    def delete(self, url_parts, **kwargs):
        return self._request("DELETE", url_parts, **kwargs)
