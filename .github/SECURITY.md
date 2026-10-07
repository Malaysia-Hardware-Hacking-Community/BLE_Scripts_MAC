# Security Policy

WAMBLE is Bluetooth Low Energy tooling. It can read from and write to real
devices, and the `wamble.exploits` package contains working proof-of-concept
attacks. This policy covers two separate things: how to use WAMBLE responsibly,
and how to report a security problem in WAMBLE itself.

## Responsible use

Only point WAMBLE at devices you own or have written permission to test. The
scanning and read-only tools are low risk, but the write and exploit tools
change device state and some of them make that change stick. Testing someone
else's device without permission is likely illegal where you live, and it is not
something this project supports.

The proof-of-concept scripts exist so that owners can understand and demonstrate
real weaknesses in their own hardware. The exploit scripts refuse to transmit
until you pass a flag that asserts you own the device or have permission to test
it. Please keep that honest.

If you publish findings, follow coordinated disclosure: tell the vendor first,
give them reasonable time to fix the problem, and leave out any detail that would
help someone attack a device they do not own.

## Reporting a vulnerability in WAMBLE

If you find a security problem in WAMBLE's own code, for example a flaw that
could harm the person running it, please report it privately rather than opening
a public issue.

Email mhhc.org@gmail.com with:

- a description of the problem and why it matters
- the steps to reproduce it
- the WAMBLE version or commit, your operating system, and your Python version

You can expect an acknowledgement within about a week. This is a small hobby
project, so fixes are best effort, but genuine security reports are taken
seriously and credited if you would like.

Please do not include details of third-party device vulnerabilities in a WAMBLE
report. Those belong with the device vendor through coordinated disclosure.

## Supported versions

WAMBLE does not yet publish tagged releases. Security fixes land on the default
branch, so running the latest commit is the best way to stay current.
