======================
Ironic Baremetal Guest
======================

Networking-Ansible can be used as the ML2 driver that configures the
switch that baremetal guests are cabled to. These guests need to have their
port configuration updated depending on their deployment configuration and status.

In this section, the ironic baremetal use case will be exercised in a set of example
commands to show how end users can use ironic to provision baremetal nodes using
networking-ansble to configure the guest's switch port. Networking-Ansible is used by
ironic to first assign a baremetal guest's switchport to the Ironic provisoning
network to provision the baremetal guest. After provisoning, the baremetal
guest's switchport is assigned to the VLAN(s) assigned by Neutron to the guest's
tenant network(s).


Guest's Port in Access Mode
~~~~~~~~~~~~~~~~~~~~~~~~~~~

This first example shows deploying a guest with Ironic using an administrator supplied
baremetal guest using a single network. The end user's experience using networking-ansible
is via Neutron and Nova. Nova will select a baremetal node and configure the guest's
switchport will be configured in access mode using the assigned VLAN designated by neutron
from the supplied tenant network.


#. An administrator will provide Ironic node(s) that are available for
   provisioning and a baremetal flavor.

    .. code-block:: console

      openstack baremetal node list
      openstack flavor list

#. Create a tenant VLAN network and subnet that uses the physical network the guest is attached to.

    .. code-block:: console

      openstack network create --provider-network-type vlan --provider-physical-network datacentre my-tenant-net
      openstack subnet create --network tenant-net --subnet-range 192.168.37.0/24 --allocation-pool start=192.168.37.10,end=192.168.37.20 tenant-subnet

#. Execute server create using the tenant network just created. This assumes
   disk images and keypairs are already created and available.

    .. code-block:: console

      openstack server create --image a-baremetal-image --flavor baremetal --nic net-id={my-tenant-net uuid} --key-name my-keypair bm-instance


Guest's Port in Trunk Mode
~~~~~~~~~~~~~~~~~~~~~~~~~~

This second example shows deploying a guest with Ironic using an administrator supplied
baremetal guest using multiple networks on a single switchport. The the guest's
switchport will be configured in trunk mode using the assigned VLANs designated by neutron
from the supplied networks.


#. An administrator will provide Ironic node(s) that are available for
   provisioning and a baremetal flavor. The administrator should also
   ensure the trunk service plugin is enabled.

    .. code-block:: console

      openstack baremetal node list
      openstack flavor list

#. Create a primary tenant VLAN network, a secondary tenant network, and subnets for each that uses the physical network the guest is attached to.

    .. code-block:: console

      openstack network create --provider-network-type vlan --provider-physical-network datacentre primary-tenant-net
      openstack network create --provider-network-type vlan --provider-physical-network datacentre secondary-tenant-net
      openstack subnet create --network primary-tenant-net --subnet-range 192.168.3.0/24 --allocation-pool start=192.168.3.10,end=192.168.3.20 primary-tenant-subnet
      openstack subnet create --network secondary-tenant-net --subnet-range 192.168.7.0/24 --allocation-pool start=192.168.7.10,end=192.168.7.20 secondary-tenant-subnet

#. Create a port and create a trunk assigning the port to the trunk as the parent port.

    .. code-block:: console

      openstack port create --network primary-tenant-net primary-port
      openstack network trunk create --parent-port primary-port my-trunk

#. Create a port for the secondary network and add it as a subport to the trunk.

    .. code-block:: console

      openstack port create --network secondary-tenant-net secondary-port
      openstack network trunk set --subport port=secondary-port,segmentation-type=vlan,segmentation-id=1234 my-trunk

#. Execute server create using the port ID of the primary port in the trunk. This assumes
   disk images and keypairs are already created and available.

    .. code-block:: console

      openstack server create --image a-baremetal-image --flavor baremetal --port primary-port --key-name my-keypair bm-instance
