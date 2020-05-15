# Local development environment

Configure a local network appliance and a devstack vm, configured appropriately

# Setup

Install libvirt and ansible

```sudo dnf install -y libvirt ansible```

Copy appliance images to ~/.localvm/base_images/[appliance]

```
mkdir -p ~/.localvm/base_images
cp vqfx10k-pfe.img ~/.localvm/base_images/vqfx10k-pfe
cp vqfx10k-re.img ~/.localvm/base_images/vqfx10k-re
```

# Usage

To create environment:

`./build`

To destroy current environment:

`./clean`

