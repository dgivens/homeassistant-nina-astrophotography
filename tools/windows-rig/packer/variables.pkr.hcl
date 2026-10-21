# rig.py passes the paths; the rest have defaults.

variable "iso_path" {
  type        = string
  description = "The Windows Evaluation ISO. Not redistributable: each user downloads their own."
}

variable "iso_sha256" {
  type        = string
  description = "SHA256 of the ISO. The default is the IoT Enterprise LTSC 2024 Evaluation, ARM64, which Microsoft publishes no working hash for."
  default     = "3dcdba9c9c0aa0430d4332b60c9afcb3cd613d648a49cbba2d4ef7b5978f32e8"
}

variable "image_index" {
  type        = number
  description = "The install.wim index to install."
  default     = 1
}

variable "arch" {
  type        = string
  description = "The guest's processorArchitecture in the answer file: arm64 or amd64."
  default     = "arm64"
}

variable "drivers_dir" {
  type        = string
  description = "A directory holding one folder of virtio drivers per driver, for the guest's architecture."
}

variable "downloads_dir" {
  type        = string
  description = "A directory holding provision/downloads.json's files, served to the guest so that a rebuild downloads nothing."
}

variable "qemu_binary" {
  type        = string
  description = "scripts/qemu-with-tpm.sh, which adds the TPM, display and USB devices to Packer's command line."
}

variable "efi_firmware_code" {
  type        = string
  description = "QEMU's AArch64 UEFI firmware."
}

variable "efi_firmware_vars" {
  type        = string
  description = "The template the build's EFI variables are copied from."
}

variable "output_directory" {
  type        = string
  description = "Where Packer writes the image and its EFI variables. It must not exist."
}

variable "vm_name" {
  type    = string
  default = "base.qcow2"
}

variable "cpus" {
  type    = number
  default = 8
}

variable "memory_gb" {
  type    = number
  default = 16
}

variable "disk_size_gb" {
  type    = number
  default = 100
}

variable "headless" {
  type    = bool
  default = true
}

variable "ssh_public_key" {
  type        = string
  description = "Authorised for Administrator over SSH."
}

# The VM is reachable only through forwards on the host's loopback interface,
# so this password protects nothing; it is also the stored autologon password.
variable "build_password" {
  type      = string
  default   = "rig-build-only-Win11!"
  sensitive = true
}
