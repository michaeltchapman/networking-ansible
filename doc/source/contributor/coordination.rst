================
Coordination
================
Networking-ansible uses the tooz library to prevent multiple neutron processes
from modifying a single switch at any given time. While some switches are
able to handle concurrent updates, others will fail and leave the system in
inconsistent state.

Distributed locks
~~~~~~~~~~~~~~~~~
In keeping with the general config management philosophy of using idempotency
and eventual consistency, networking-ansible has each request wait until it
can acquire a lock for the switch it is proposed to modify. Because there is
no global queue for requests, the order in which requests receive that lock
is unpredictable, and the time a request may have to wait can vary up to the
tooz lock timeout (30 seconds).

Since requests are delayed in this manner, their operation may be superceded
or otherwise out of date by the time the lock is acquired and modification
of the switch can begin. As an example, if a user A submits a request to create
a network, user B submits a request to create a port, and finally user B
submits a request to delete that port, while user A's request is being handled,
both the create and the delete of a single port will be waiting for the lock.
Since there is no strict ordering, the delete could execute before the create,
which could result in a port that the user no longer desired remaining in the
system.

To combat this type of issue, each request will re-request relevant data from
the neutron DB after acquiring its lock and modify its behavior accordingly.
In the above example, if the create executes first, it will search for a port
with its ID in the DB, fail to find one, and exit without modifying the switch.
Then the delete will execute, check if there is any active neutron port
assigned to that switch port and if there is not, will ensure that the port
does not have any VLANs allowed.

The most complex operations to work with in this manner are deletes, since
before running any task it is imperative that checks are done to see if
other users are utilising the underlying switch resource. In the above example
if we did not do this, a third user that had created a neutron port on the same
physical port as user B might have the VLANs removed from their port against
their wishes.
