# Security policy

Please do **not** disclose a vulnerability in a public issue. Use [GitHub's private vulnerability reporting](https://github.com/WinsperApp/winsper/security/advisories/new) if available, or email [help@winsper.app](mailto:help@winsper.app) with a concise reproduction and affected version. Do not attach real recordings, dictated text, credentials, or other users' data.

We will acknowledge reports and work on a fix before public disclosure. Supported security fixes target the latest published release; older versions may need to update.

Winsper runs speech recognition and its default AI Polish locally. Downloads, updates, and support are separate network flows. A user-configured remote model endpoint is outside this default local boundary.
