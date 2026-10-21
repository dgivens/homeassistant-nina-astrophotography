# The rig's base image: Windows from the Evaluation ISO, updated, then
# provision/provision.ps1. rig.py runs this with swtpm already listening.

packer {
  required_version = ">= 1.10.0"
  required_plugins {
    qemu = {
      # The qemu wrapper rewrites the command line this plugin generates.
      version = "~> 1.1"
      source  = "github.com/hashicorp/qemu"
    }
  }
}

source "qemu" "rig" {
  vm_name          = var.vm_name
  output_directory = var.output_directory

  iso_url      = var.iso_path
  iso_checksum = "sha256:${var.iso_sha256}"

  cpus           = var.cpus
  memory         = var.memory_gb * 1024
  disk_size      = "${var.disk_size_gb}G"
  format         = "qcow2"
  disk_interface = "virtio"
  net_device     = "virtio-net-pci"
  # Windows discards what it deletes, and Packer's compaction then leaves it
  # out of the image.
  disk_discard       = "unmap"
  disk_detect_zeroes = "unmap"

  # HVF cannot give the guest virtualisation extensions, so the machine type
  # must not ask for them.
  qemu_binary  = var.qemu_binary
  machine_type = "virt,gic-version=max"
  accelerator  = "hvf"
  cpu_model    = "host"

  efi_boot          = true
  efi_firmware_code = var.efi_firmware_code
  efi_firmware_vars = var.efi_firmware_vars

  # Setup reads Autounattend.xml from the root of any attached disc.
  cd_content = {
    "Autounattend.xml" = templatefile("${abspath(path.root)}/autounattend.xml.pkrtpl", {
      arch        = var.arch
      image_index = var.image_index
      password    = var.build_password
    })
  }
  cd_files = [var.drivers_dir]
  cd_label = "UNATTEND"

  # The guest reaches the host's loopback interface at 10.0.2.2, QEMU's
  # user-mode gateway; PackerHTTPAddr would name the bind address instead.
  http_directory    = var.downloads_dir
  http_bind_address = "127.0.0.1"

  communicator   = "winrm"
  winrm_username = "Administrator"
  winrm_password = var.build_password
  winrm_timeout  = "2h"

  # No sysprep (W-07): the image keeps its Administrator, so Packer shuts it down.
  shutdown_command = "shutdown /s /t 10 /f /d p:4:1 /c \"Packer shutdown\""
  shutdown_timeout = "30m"

  headless = var.headless
  display  = var.headless ? null : "cocoa,zoom-to-fit=on"

  # The firmware boots the ISO only if a key is pressed within a few seconds.
  # The presses stop before Setup's window opens: its install page focuses
  # Cancel, and an Enter there abandons the install half-written.
  boot_wait    = "1s"
  boot_command = [for i in range(6) : "<enter><wait1>"]
}


build {
  sources = ["source.qemu.rig"]

  provisioner "powershell" {
    inline = ["New-Item -ItemType Directory -Force -Path C:\\rig\\provision, C:\\rig\\fixtures | Out-Null"]
  }

  provisioner "file" {
    source      = "${abspath(path.root)}/../provision/"
    destination = "C:\\rig\\provision\\"
  }

  provisioner "file" {
    source      = "${abspath(path.root)}/../../../tests/fixtures/rig/"
    destination = "C:\\rig\\fixtures\\"
  }

  # Every step runs as a scheduled task holding the password: Windows refuses
  # to install features and updates from a plain remote session.
  provisioner "powershell" {
    elevated_user     = "Administrator"
    elevated_password = var.build_password
    environment_vars  = ["RIG_MIRROR=http://10.0.2.2:${build.PackerHTTPPort}"]
    inline            = ["& C:\\rig\\provision\\windows-update.ps1"]
  }

  provisioner "windows-restart" {
    restart_timeout = "1h"
  }

  provisioner "powershell" {
    elevated_user     = "Administrator"
    elevated_password = var.build_password
    environment_vars = [
      "RIG_MIRROR=http://10.0.2.2:${build.PackerHTTPPort}",
      "RIG_SSH_PUBLIC_KEY=${var.ssh_public_key}",
      "RIG_PASSWORD=${var.build_password}",
    ]
    inline = ["& C:\\rig\\provision\\provision.ps1"]
  }

  provisioner "powershell" {
    inline = ["Remove-Item C:\\rig\\downloads -Recurse -Force -ErrorAction SilentlyContinue"]
  }
}
