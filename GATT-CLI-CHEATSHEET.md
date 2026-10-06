# gatt_cli cheatsheet

gatt_cli is the interactive prompt for poking at a BLE device: read a value,
write some bytes, subscribe to notifications.

## Starting it

```bash
python gatt_cli.py "GBK_H619A"          # match by name (or paste an address)
python gatt_cli.py "GBK_H619A" --keepalive 0   # turn off the idle keep-alive ping
```

It connects, dumps the GATT tree, and drops you at a `[gatt]` prompt. Paste works
(Cmd-V), and anything after a `#` on a line is ignored, so you can paste a command
with a note stuck to the end of it. Ctrl-C always gets you out cleanly without
leaving the terminal in a weird state.

---

## The commands

`HANDLE_OR_UUID` is either a handle (`13`, `0x0d`) or a piece of a UUID (`2b11`,
`ffc1`). You get handles from `characteristics` or from `enum_ble.py`.

| Command | What it does | Example |
|---|---|---|
| `services` | List services (UUID, handle, #chars) | `services` |
| `characteristics` | List characteristics (UUID, handle, properties) | `characteristics` |
| `descriptors` | List descriptors (e.g. CCCD `2902`) | `descriptors` |
| `read HANDLE_OR_UUID` | Read a value; prints hex + text | `read 2b10` |
| `write-req HANDLE_OR_UUID HEX` | Write *with* response, needs the `write` property | `write-req 2a00 4e657744` |
| `write-cmd HANDLE_OR_UUID HEX` | Write *without* response, needs `write-without-response` | `write-cmd 2b11 3301010000000000000000000000000000000033` |
| `notify HANDLE_OR_UUID` | Subscribe; updates stream in until `unnotify` | `notify 18` |
| `indicate HANDLE_OR_UUID` | Subscribe (acknowledged notifications) | `indicate 18` |
| `unnotify HANDLE_OR_UUID` | Stop a subscription (works even while updates scroll past) | `unnotify 18` |
| `reconnect` | Bring back a dropped link and re-arm subscriptions | `reconnect` |
| `help` | Show the command list | `help` |
| `quit` / `exit` | Disconnect and leave (Ctrl-C / Ctrl-D also work) | `quit` |

### Which write do I use?

Run `characteristics` and look at the Properties column:

- Says `Write` → use `write-req`.
- Says `Write Without Response` → use `write-cmd`.
- Has both → either works, though control points usually expect `write-cmd`.

Pick the wrong one and you get an error naming the property the characteristic is
missing. `HEX` is raw bytes with no `0x` and no spaces: `3301010000…33`.

---

## Payloads: the `0x33` LED framing

On the `GBK_H619A` controller the characteristic you write to is `2b11` (handle
13). It's write-without-response, so you reach it with `write-cmd`. Everything it
accepts is a 20-byte packet shaped like this:

```
byte 0      : 0x33          control-write marker
byte 1      : command       0x01 power · 0x04 brightness · 0x05 color
bytes 2..N  : command data  (see below)
bytes ..18  : 0x00          zero padding out to 19 bytes
byte 19     : checksum       XOR of bytes 0..18
```

| Command byte | Meaning | Data bytes |
|---|---|---|
| `01` | Power | `01` = on, `00` = off |
| `04` | Brightness | one byte `00` to `ff` (0 to 255) |
| `05 02` | Colour (manual mode) | `RR GG BB` |

### Why it's shaped like that

None of this is arbitrary, and once the pieces click you can build your own
packets instead of copying mine.

- **It's always 20 bytes** because that's what one BLE write holds at the default
  MTU (23, minus the 3-byte ATT header). One packet per command, nothing to
  fragment. Send some other length and the firmware just ignores it.
- **The first byte, `0x33`, says what kind of frame this is.** The firmware sorts
  incoming frames by that leading byte, and `0x33` is the "set something" write.
  Drop it and lead with `01 01` instead, and the device has no idea you're handing
  it a command.
- **Byte 1 is the command, and whatever follows are its arguments.** `01` is power
  (`01` on, `00` off), `04` is brightness (a single `00` to `ff`), `05` is colour.
  Colour wants a sub-mode byte first. `02` is plain static RGB, while the other
  modes drive scenes, segments, or music. After the sub-mode comes `RR GG BB`.
- **The zeros in the middle are just padding** to fill out the fixed 20 bytes.
  They don't carry anything.
- **The last byte is an XOR checksum** of the other 19. The firmware recomputes it
  and throws the frame away if it doesn't match, which is exactly why you can't
  spray random bytes at `2b11` and expect a reaction. Every packet has to end
  with the right XOR. Quick check: `33 ^ 01 ^ 01` is `0x33`, so the power-on
  packet ends in `33`; switch that data byte to `00` for off and the checksum
  moves to `0x32`.

### Where this came from

I didn't reverse this from scratch. The 20-byte `0x33`/XOR format is the
well-known protocol for this kind of RGB controller, and it has been reimplemented
in plenty of open-source BLE-LED projects. What I did was confirm it on your actual
unit: `write-cmd 2b11 3301010000…33` turned the light on, `…32` turned it back
off. So the frame type, the command byte, the padding, and the checksum rule are
all verified against the real hardware, not copied off a wiki and hoped for.

If you ever meet a device whose format you *don't* know, the toolkit is enough to
work it out. Find the writable characteristic with `enum_ble`, `notify` its notify
characteristic while you drive the official app, and watch the frames come in.
Then replay them, change a byte at a time, and see how the device reacts. To spot
a checksum, flip a single data byte: if the device suddenly ignores a frame it
accepted a second ago, the trailing byte is guarding the rest.

### Payloads ready to paste (after `write-cmd 2b11 `)

| Effect | Payload |
|---|---|
| Power **on** | `3301010000000000000000000000000000000033` |
| Power **off** | `3301000000000000000000000000000000000032` |
| Brightness 100% | `3304ff00000000000000000000000000000000c8` |
| Brightness 50% | `33048000000000000000000000000000000000b7` |
| Brightness 1% | `3304010000000000000000000000000000000036` |
| Colour red | `330502ff000000000000000000000000000000cb` |
| Colour green | `33050200ff0000000000000000000000000000cb` |
| Colour blue | `3305020000ff00000000000000000000000000cb` |
| Colour white | `330502ffffff00000000000000000000000000cb` |
| Colour warm amber | `330502ff8c000000000000000000000000000047` |

```
[gatt] write-cmd 2b11 3301010000000000000000000000000000000033   # power on
[gatt] write-cmd 2b11 330502ff000000000000000000000000000000cb   # red
[gatt] write-cmd 2b11 3301000000000000000000000000000000000032   # power off
```

**Need one that's not in the table?** The checksum is a plain XOR, so:

```python
def pkt(cmd, *data):
    body = bytes([0x33, cmd, *data]); body += bytes(19 - len(body))
    c = 0
    for b in body: c ^= b
    return (body + bytes([c])).hex()

pkt(0x05, 0x02, 0x10, 0x80, 0xff)   # a custom colour
```

---

## Writing to other things

A payload is just whatever bytes a characteristic expects, and that's different on
every device. Two cases worth calling out:

- **Text**, like a writable Device Name (`2a00`): spell it in hex. `"NewD"` is
  `4e657744`, so `write-req 2a00 4e657744`.
- **Control points you don't understand**, like the Xiaomi scale's vendor
  characteristics: don't just write to them. Enumerate first and watch the
  `notify` traffic until the format is clear. A blind write to a scale could
  change settings or firmware state.

### A typical session

```
[gatt] characteristics            # find the control char + its write type
[gatt] read 2b10                  # read current state
[gatt] notify 18                  # watch what the device reports
[gatt] write-cmd 2b11 3301010000000000000000000000000000000033   # act
[gatt] unnotify 18
[gatt] quit
```
