# Code signing policy

Winsper 1.1.2's direct Windows installer is **unsigned**. The release includes a SHA-256 checksum and source-bound inventory so you can verify the download, but those files are not a substitute for a trusted Windows signature. Do not disable antivirus protection to install Winsper.

The project will only call a release “signed” after its installer and application binaries have valid, timestamped Authenticode signatures from an approved trusted signing route and the published download has been checked again. Signing changes the binary and its checksum; a signed build would need its own release artifacts and update manifest, not a silent replacement of the existing immutable 1.1.2 download.

For a direct GitHub/website installer, the preferred no-cost route is an application to [SignPath Foundation](https://signpath.org/). Approval is not automatic; the project must meet its open-source, provenance, maintenance, privacy, and signing-policy conditions. SignPath Foundation would be the Windows publisher. We will not claim sponsorship or display its signing credit unless accepted.

For a Microsoft Store MSIX, Microsoft signs the package after Store certification. That does **not** sign the separate direct EXE installer. A Store submission requires its own identity and certification process. Self-signed certificates are for development or managed internal deployments, not public trust.

See the [download page](https://winsper.app/download/) for the current signature status and checksum, and the [1.1.2 GitHub release](https://github.com/WinsperApp/winsper/releases/tag/v1.1.2) for the source-bound inventory and LGPL materials.
