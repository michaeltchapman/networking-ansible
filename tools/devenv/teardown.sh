#!/usr/bin/bash

set -e
set -x

pushd centos-devstack-vqfx
vagrant destroy -f controller
popd
