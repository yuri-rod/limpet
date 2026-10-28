# Changelog

## Unreleased

- Separate GitHub releases from PyPI publication. The publish workflow now requires
  a manual dispatch with an existing tag that matches the package version.

## 0.1.1

- Require the sending client's subscription before forwarding input or resize
  requests, keeping mutations inside subscription cleanup.
- Reject alternate unspecified IPv4/IPv6 bind addresses and invalid host types.
- Return protocol errors for malformed message types and invalid binary UTF-8
  without disconnecting the client.
- Require websockets 13.1 or later, matching the asyncio server API and its
  handshake-rejection behavior. Verify the minimum on Python 3.10 in CI.
- Add a synthetic loopback example, clarify the client protocol and operating
  limits, and correct launchd documentation without changing restart behavior.
- Include the example and operating guidance in source distributions. Restrict
  CI token permissions to repository reads.
- Add a PyPI trusted publishing workflow,
  triggered by a published GitHub release or manual dispatch.
