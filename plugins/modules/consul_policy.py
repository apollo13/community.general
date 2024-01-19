#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright (c) 2022, Håkon Lerring
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = """
module: consul_policy
short_description: Manipulate Consul policies
version_added: 7.2.0
description:
 - Allows the addition, modification and deletion of policies in a consul
   cluster via the agent. For more details on using and configuring ACLs,
   see U(https://www.consul.io/docs/guides/acl.html).
author:
  - Håkon Lerring (@Hakon)
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
      - Whether the policy should be present or absent.
    choices: ['present', 'absent']
    default: present
    type: str
  valid_datacenters:
    description:
      - Valid datacenters for the policy. All if list is empty.
    type: list
    elements: str
  name:
    description:
      - The name that should be associated with the policy, this is opaque
        to Consul.
    required: true
    type: str
  description:
    description:
      - Description of the policy.
    type: str
  rules:
    type: str
    description:
      - Rule document that should be associated with the current policy.
"""

EXAMPLES = """
- name: Create a policy with rules
  community.general.consul_policy:
    host: consul1.example.com
    token: some_management_acl
    name: foo-access
    rules: |
        key "foo" {
            policy = "read"
        }
        key "private/foo" {
            policy = "deny"
        }

- name: Update the rules associated to a policy
  community.general.consul_policy:
    host: consul1.example.com
    token: some_management_acl
    name: foo-access
    rules: |
        key "foo" {
            policy = "read"
        }
        key "private/foo" {
            policy = "deny"
        }
        event "bbq" {
            policy = "write"
        }

- name: Remove a policy
  community.general.consul_policy:
    host: consul1.example.com
    token: some_management_acl
    name: foo-access
    state: absent
"""

RETURN = """
operation:
    description: The operation performed on the policy.
    returned: changed
    type: str
    sample: update
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.community.general.plugins.module_utils.consul import (
    OPERATION_READ,
    _ConsulModule,
    auth_argument_spec,
)

_ARGUMENT_SPEC = {
    "name": dict(required=True),
    "description": dict(required=False, type="str"),
    "rules": dict(type="str"),
    "valid_datacenters": dict(type="list", elements="str"),
    "state": dict(default="present", choices=["present", "absent"]),
}
_ARGUMENT_SPEC.update(auth_argument_spec())


class ConsulPolicyModule(_ConsulModule):
    api_endpoint = "acl/policy"
    result_key = "policy"
    unique_identifier = "id"

    def endpoint_url(self, operation, obj=None):
        if operation == OPERATION_READ:
            return [self.api_endpoint, "name", self.module.params["name"]]
        return super().endpoint_url(operation, obj)


def main():
    module = AnsibleModule(
        _ARGUMENT_SPEC,
        supports_check_mode=True,
    )
    consul_module = ConsulPolicyModule(module)
    consul_module.execute()


if __name__ == "__main__":
    main()
