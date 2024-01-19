#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2024, Florian Apolloner (@apollo13)
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = """
module: consul_token
short_description: Manipulate Consul tokens
version_added: 0.0.0
description:
 - Allows the addition, modification and deletion of tokens in a consul
   cluster via the agent. For more details on using and configuring ACLs,
   see U(https://www.consul.io/docs/guides/acl.html).
author:
  - Florian Apolloner (@apollo13)
extends_documentation_fragment:
  - community.general.consul
  - community.general.attributes
attributes:
  check_mode:
    support: full
  diff_mode:
    support: partial
options:
  state:
    description:
      - Whether the token should be present or absent.
    choices: ['present', 'absent']
    default: present
    type: str
  accessor_id:
    description:
      - Specifies a UUID to use as the token's Accessor ID.
        If not specified a UUID will be generated for this field.
    type: str
  secret_id:
    description:
      - Specifies a UUID to use as the token's Secret ID.
        If not specified a UUID will be generated for this field.
    type: str
  description:
    description:
      - Free form human readable description of the token.
    type: str
  policies:
    description:
      - The list of policy names that should be applied to the token.
    type: list
    elements: str
  roles:
    description:
      - The list of role names that should be applied to the token.
    type: list
    elements: str
  templated_policies:
    description:
      - The list of templated policies that should be applied to the role.
    type: list
    elements: dict
  service_identities:
    description:
      - The list of service identities that should be applied to the token.
    type: list
    elements: dict
  node_identities:
    description:
      - The list of node identities that should be applied to the token.
    type: list
    elements: dict    
  local:
    description:
      - If true, indicates that the token should not be replicated globally 
        and instead be local to the current datacenter.
    type: bool
  expiration_ttl:
    description:
      - This is a convenience field and if set will initialize the O(expiration_time).
        Can be specified in the form of "60s" or "5m" (i.e., 60 seconds or 5 minutes,
        respectively). Ingored when the token is updated!
    type: str
"""

EXAMPLES = """
- name: Create / Update a token by accessor_id
  community.general.consul_token:
    state: present
    accessor_id: 07a7de84-c9c7-448a-99cc-beaf682efd21
    token: 8adddd91-0bd6-d41d-ae1a-3b49cfa9a0e8
    roles: [role1, role2]
    service_identities:
      - service_name: service1
        datacenters: [dc1, dc2]
    node_identities:
      - node_name: node1
        datacenters: [dc1, dc2]            

- name: Delete a token
  community.general.consul_token:
    state: absent
    accessor_id: 07a7de84-c9c7-448a-99cc-beaf682efd21
    token: 8adddd91-0bd6-d41d-ae1a-3b49cfa9a0e8        
"""

RETURN = """
token:
    description: The token as returned by the consul HTTP API
    returned: always
    type: dict
    sample:
        AccessorID: 07a7de84-c9c7-448a-99cc-beaf682efd21
        CreateIndex: 632
        CreateTime: "2024-01-14T21:53:01.402749174+01:00"
        Description: Testing
        Hash: rj5PeDHddHslkpW7Ij4OD6N4bbSXiecXFmiw2SYXg2A=
        Local: false
        ModifyIndex: 633
        SecretID: bd380fba-da17-7cee-8576-8d6427c6c930, 
        ServiceIdentities: [{"ServiceName": "test"}]
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.community.general.plugins.module_utils.consul import (
    RequestError,
    _ConsulModule,
    auth_argument_spec,
    camel_case_key,
)


class ConsulTokenModule(_ConsulModule):
    api_endpoint = "acl/token"
    result_key = "token"
    unique_identifier = "accessor_id"

    def map_param(self, k, v, is_update):
        def helper(item):
            return {camel_case_key(k): v for k, v in item.items()}

        if k in {"policies", "roles"} and v:
            v = [{"Name": i} for i in v]
        if k in {"templated_policies", "node_identities", "service_identities"} and v:
            v = [helper(i) for i in v]
        if is_update and k == "expiration_ttl":
            return  # expiration_ttl not supported on update

        return super().map_param(k, v, is_update)

    def read_object(self):
        try:
            return super().read_object()
        except RequestError as e:
            if e.status == 403 and b"token does not exist" in e.response_data:
                return

    def needs_update(self, api_obj, module_obj):
        # SecretID is usually not supplied
        if "SecretID" not in module_obj and "SecretID" in api_obj:
            del api_obj["SecretID"]
        # We solely compare roles and policies by name
        if "Roles" in api_obj:
            api_obj["Roles"] = [{"Name": i["Name"]} for i in api_obj["Roles"]]
        if "Policies" in api_obj:
            api_obj["Policies"] = [{"Name": i["Name"]} for i in api_obj["Policies"]]
        # ExpirationTTL is only supported on create, not for update
        # it writes to ExpirationTime, so we need to remove that as well
        if "ExpirationTTL" in module_obj:
            del module_obj["ExpirationTTL"]
        return super().needs_update(api_obj, module_obj)


_ARGUMENT_SPEC = {
    "description": dict(),
    "accessor_id": dict(),
    "secret_id": dict(no_log=True),
    "roles": dict(type="list", elements="str"),
    "policies": dict(type="list", elements="str"),
    "templated_policies": dict(type="list", elements="dict"),
    "node_identities": dict(type="list", elements="dict"),
    "service_identities": dict(type="list", elements="dict"),
    "local": dict(type="bool"),
    "expiration_ttl": dict(type="str"),
    "state": dict(default="present", choices=["present", "absent"]),
}
_ARGUMENT_SPEC.update(auth_argument_spec())


def main():
    module = AnsibleModule(
        _ARGUMENT_SPEC,
        required_if=[("state", "absent", ["accessor_id"])],
        supports_check_mode=True,
    )
    consul_module = ConsulTokenModule(module)
    consul_module.execute()


if __name__ == "__main__":
    main()
