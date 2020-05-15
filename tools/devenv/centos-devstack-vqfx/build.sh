#!/bin/bash
set -x
set -e
ANSIBLE_STRICT_HOST_KEY_CHECKING=False ansible-playbook devstack.yml -e @vars/devstack.yml -vvv
