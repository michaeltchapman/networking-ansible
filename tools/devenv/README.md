# VQFX development environment

This is a set of vagrant managed environments. There are currently
three machines:

 - vqfx
 - vqfx-pfe
 - controller

each of which can be created using vagrant up [machine name]

# Requirements

Install vagrant-libvirt. Acquire vqfx pfe and re boxes from Juniper site
and convert to libvirt then put into vagrant .box packages.

# Usage

``vagrant up vqfx; vagrant up vqfx-pfe; vagrant up controller``

Deployment must be done in this order, since the pfe and re will sync in
the background and this will cause timeouts in the vqfx provisioning. The
controller will use the vqfx in order to deploy ironic baremetal nodes and
do connectivity tests, so must be deployed last.




