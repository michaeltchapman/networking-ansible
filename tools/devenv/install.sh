#!/usr/bin/bash

set -e
set -x

if ! command -v git; then
  yum install -y git
fi

if ! command -v ansible; then
  yum install -y ansible
fi
