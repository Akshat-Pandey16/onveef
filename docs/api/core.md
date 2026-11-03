# Sans-IO core

None of these modules touches the network: `envelopes` turns arguments into request
strings, `parsers` turns response strings into dicts, and the rest work on those dicts —
merging a partial change into a configuration and checking it against the device's options
(`updates`), PTZ geometry (`ptz`), and the ONVIF parts of RTSP replay (`replay`). All pure
functions, which is why device behaviour can be verified from recorded XML.

## Request builders

::: onveef.envelopes

## Response parsers

::: onveef.parsers

## Read-modify-write

::: onveef.updates

## PTZ geometry and capabilities

::: onveef.ptz

## Replay over RTSP (Profile G)

::: onveef.replay

## Physical Access Control (Profile A/C)

::: onveef.pacs
