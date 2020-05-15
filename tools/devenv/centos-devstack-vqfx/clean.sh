#!/bin/bash

virsh destroy local_vqfx
virsh undefine local_vqfx
virsh destroy local_vqfx_pfe
virsh undefine local_vqfx_pfe
virsh destroy local_controller
virsh undefine local_controller
