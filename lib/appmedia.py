"""The media relay's checks: what a code app may have the guide's player
decode.

Everything Qt's player reads from an app came through the relay, and the
relay passes only:

- media that passes a bounded structure check for one allowlisted format
  (header checks only: no sample tables, no decoding), by how it was
  reached: the play URL itself ("direct"), an HLS segment ("segment") or an
  EXT-X-MAP initialization section ("map");
- AES-128 keys reached from a rewritten EXT-X-KEY: exactly 16 bytes;
- HLS playlists, parsed fail-closed against a tag allowlist (RFC 8216) and
  rewritten so every URI in them is a relay path.

Pure functions, the standard library only: the helper (bin/om-pg-apprun)
does the network and keeps the table of relay ids.
"""

import re
import struct
import urllib.parse

PROBE = 65536                      # bytes the relay reads before deciding
MAX_PLAYLIST = 1024 * 1024
MAX_URIS = 20000
MAX_DEPTH = 1                      # 0: the play URL's playlist; 1: a master's child


class Refused(Exception):
    """Not something the relay passes: .code is a short slug, the message a
    plain sentence"""

    def __init__(self, code, text):
        super().__init__(text)
        self.code = code


def sniff(data):
    """The play URL's first bytes: an HLS playlist, or media to check"""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    if data.startswith(b"#EXTM3U") and (len(data) == 7 or data[7:8] in (b"\n", b"\r")):
        return "playlist"
    return "media"


# ---- ISO BMFF (MP4, M4A, MOV; fMP4) ----------------------------------------

# the top-level boxes a direct file may have after its ftyp
DIRECT_TOP = {b"moov", b"mdat", b"free", b"skip", b"wide", b"uuid", b"meta", b"pdin", b"moof",
              b"mfra", b"sidx", b"styp", b"emsg", b"prft", b"udta"}
# between a segment's styp and its first moof (FFmpeg's own HLS segments are
# styp sidx sidx moof mdat): segment index and event boxes only
SEGMENT_INDEX = {b"sidx", b"ssix", b"prft", b"emsg"}
# after a segment's first moof/mdat pair
SEGMENT_MORE = {b"moof", b"mdat", b"emsg", b"prft", b"sidx", b"ssix", b"free", b"skip"}
MAX_FTYP = 4096


def _printable(t):
    return len(t) == 4 and all(0x20 <= c <= 0x7e for c in t)


def _boxes(data, complete, start=0, end=None):
    """The boxes in data[start:end], walked by their headers: a list of
    (type, offset, size or None when it runs to the end, fits) and whether
    the walk stopped at the probe's edge. A box running past the probe ends
    the walk (that's fine); one running past a complete resource is Bad."""
    end = len(data) if end is None else end
    out = []
    pos = start
    while pos < end:
        if end - pos < 8:
            if complete or end < len(data):
                raise Refused("box", "an ISO BMFF box header is cut short")
            return out, True
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        if not _printable(kind):
            raise Refused("box", "an ISO BMFF box has a type that isn't four printable letters")
        head = 8
        if size == 1:
            if end - pos < 16:
                if complete or end < len(data):
                    raise Refused("box", "an ISO BMFF box's 64-bit size is cut short")
                return out, True
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            head = 16
            if size < 16 or size >= 1 << 62:
                raise Refused("box", "an ISO BMFF box has an impossible 64-bit size")
        elif size == 0:
            # to the end of the file: only ever the last box
            out.append((kind, pos, None, False))
            return out, not complete
        elif size < 8:
            raise Refused("box", "an ISO BMFF box has an impossible size")
        if kind == b"uuid" and size < head + 16:
            raise Refused("box", "a uuid box is too small for its own type")
        if pos + size > end:
            if complete or end < len(data):
                raise Refused("box", "an ISO BMFF box runs past the end of what holds it")
            out.append((kind, pos, size, False))
            return out, True
        out.append((kind, pos, size, True))
        pos += size
    return out, False


def _ftyp(data, box):
    kind, pos, size, fits = box
    if kind != b"ftyp":
        raise Refused("mp4", "an MP4 starts with its ftyp box")
    if size is None or not fits or size > MAX_FTYP or size < 16 or (size - 16) % 4:
        raise Refused("mp4", "the MP4's ftyp box isn't well formed")
    if not _printable(data[pos + 8:pos + 12]):
        raise Refused("mp4", "the MP4's brand isn't four printable letters")


def _container(data, box, needs, what):
    """A container box (moov, moof): its children walk cleanly inside it,
    and one it must have (mvhd, mfhd) is among them while all of it is seen"""
    kind, pos, size, fits = box
    if size is None:
        raise Refused(what, "the " + kind.decode() + " box has no size")
    head = 16 if struct.unpack(">I", data[pos:pos + 4])[0] == 1 else 8
    stop = pos + size if fits else len(data)
    children, cut = _boxes(data, fits, pos + head, stop)
    if fits and not any(c[0] == needs for c in children):
        raise Refused(what, "the " + kind.decode() + " box has no " + needs.decode())
    if not children and fits:
        raise Refused(what, "the " + kind.decode() + " box is empty")


def _mp4_direct(data, complete):
    boxes, cut = _boxes(data, complete)
    if not boxes:
        raise Refused("mp4", "the MP4 has no boxes")
    _ftyp(data, boxes[0])
    seen = set()
    for b in boxes[1:]:
        if b[0] not in DIRECT_TOP:
            raise Refused("mp4", "the MP4 has a top-level box (" + b[0].decode() + ") that isn't allowed")
        if b[0] == b"moov":
            if b"moov" in seen:
                raise Refused("mp4", "the MP4 has two moov boxes")
            _container(data, b, b"mvhd", "mp4")
        elif b[0] == b"moof":
            _container(data, b, b"mfhd", "mp4")
        seen.add(b[0])
    if complete and b"moov" not in seen:
        raise Refused("mp4", "the MP4 has no moov box")
    return "mp4"


def _fmp4_init(data, complete):
    boxes, cut = _boxes(data, complete)
    if len(boxes) < 2:
        raise Refused("fmp4", "an fMP4 initialization section is an ftyp box then a moov box")
    _ftyp(data, boxes[0])
    if boxes[1][0] != b"moov":
        raise Refused("fmp4", "an fMP4 initialization section is an ftyp box then a moov box")
    _container(data, boxes[1], b"mvhd", "fmp4")
    for b in boxes[2:]:
        if b[0] not in (b"free", b"skip"):
            raise Refused("fmp4", "an fMP4 initialization section has a box (" + b[0].decode() + ") after its moov")
    return "fmp4-init"


def _fmp4_segment(data, complete):
    boxes, cut = _boxes(data, complete)
    if not boxes:
        raise Refused("fmp4", "the segment has no boxes")
    i = 0
    if boxes[0][0] == b"styp":
        b = boxes[0]
        if b[2] is None or not b[3] or b[2] < 16 or (b[2] - 16) % 4 or not _printable(data[b[1] + 8:b[1] + 12]):
            raise Refused("fmp4", "the segment's styp box isn't well formed")
        i = 1
    elif boxes[0][0] not in SEGMENT_INDEX and boxes[0][0] != b"moof":
        raise Refused("fmp4", "an fMP4 segment starts with styp, an index (sidx and the like) or moof, not " + boxes[0][0].decode())
    # its index (FFmpeg's single-file segments start sidx, moof, with no styp),
    # then its first moof, which must show within the probe
    while i < len(boxes) and boxes[i][0] in SEGMENT_INDEX:
        i += 1
    if i >= len(boxes):
        # no moof within what was read (an index running past the probe, say):
        # nothing here has shown it's a media segment
        raise Refused("fmp4", "the segment shows no moof box in its first 64 KB" if cut else "the segment has no moof box")
    if boxes[i][0] != b"moof":
        raise Refused("fmp4", "the segment has a box (" + boxes[i][0].decode() + ") before its first moof")
    pairs = 0
    rest = boxes[i:]
    for n, b in enumerate(rest):
        if b[0] not in SEGMENT_MORE:
            raise Refused("fmp4", "the segment has a box (" + b[0].decode() + ") that isn't allowed")
        if b[0] == b"mdat" and (n == 0 or rest[n - 1][0] != b"moof"):
            raise Refused("fmp4", "an mdat box in the segment doesn't follow a moof")
        if b[0] == b"moof":
            _container(data, b, b"mfhd", "fmp4")
            if n + 1 < len(rest):
                if rest[n + 1][0] != b"mdat":
                    raise Refused("fmp4", "a moof box isn't followed by its mdat")
                pairs += 1
            elif complete:
                raise Refused("fmp4", "the segment's last moof has no mdat")
    if complete and pairs == 0:
        raise Refused("fmp4", "the segment has no moof and mdat pair")
    return "fmp4-segment"


# ---- MPEG audio (MP3) and AAC (ADTS) -----------------------------------------

MP3_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}
MP3_KBPS = {3: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
            2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)}
ADTS_RATES = 13                    # sampling frequency indexes 0..12


def _id3(data, complete):
    """Where the audio starts after an ID3v2 tag (0 if there's none); the
    tag must end inside the probe"""
    if not data.startswith(b"ID3"):
        return 0
    if len(data) < 10:
        raise Refused("id3", "an ID3 tag is cut short")
    major, rev, flags = data[3], data[4], data[5]
    if major not in (2, 3, 4) or rev == 0xFF:
        raise Refused("id3", "an ID3 tag has a version that doesn't exist")
    if flags & {2: 0x3F, 3: 0x1F, 4: 0x0F}[major]:
        raise Refused("id3", "an ID3 tag has flags that don't exist")
    size = 0
    for b in data[6:10]:
        if b & 0x80:
            raise Refused("id3", "an ID3 tag's size isn't synchsafe")
        size = size << 7 | b
    end = 10 + size + (10 if major == 4 and flags & 0x10 else 0)
    if end >= len(data) or end > PROBE - 8:
        raise Refused("id3", "the ID3 tag is bigger than the relay looks at, so what follows it can't be checked")
    return end


def _mp3_frame(data, pos):
    """(size, version, sample rate index) of an MPEG Layer III frame header
    at pos, or None"""
    if pos + 4 > len(data):
        return None
    h = struct.unpack(">I", data[pos:pos + 4])[0]
    if h >> 21 != 0x7FF:
        return None
    version, layer = h >> 19 & 3, h >> 17 & 3
    kbps, rate, pad, emphasis = h >> 12 & 15, h >> 10 & 3, h >> 9 & 1, h & 3
    if version == 1 or layer != 1 or kbps in (0, 15) or rate == 3 or emphasis == 2:
        return None
    bitrate = MP3_KBPS[3 if version == 3 else 2][kbps] * 1000
    hz = MP3_RATES[version][rate]
    size = (144 if version == 3 else 72) * bitrate // hz + pad
    return size, version, rate


def _mp3(data, complete):
    pos = _id3(data, complete)
    first = _mp3_frame(data, pos)
    if not first:
        raise Refused("mp3", "it isn't MPEG Layer III audio (no valid frame header where one should be)")
    nxt = pos + first[0]
    second = _mp3_frame(data, nxt)
    if not second or second[1:] != first[1:]:
        raise Refused("mp3", "an MP3 frame isn't followed by a compatible frame")
    return "mp3"


def _adts_frame(data, pos):
    """(length, id, sampling index) of an ADTS header at pos, or None"""
    if pos + 7 > len(data):
        return None
    b = data[pos:pos + 7]
    if b[0] != 0xFF or b[1] & 0xF0 != 0xF0 or b[1] & 0x06:
        return None                              # sync 0xFFF, layer 00
    mpeg_id, protection_absent = b[1] >> 3 & 1, b[1] & 1
    sampling = b[2] >> 2 & 15
    length = (b[3] & 3) << 11 | b[4] << 3 | b[5] >> 5
    head = 7 if protection_absent else 9
    if sampling >= ADTS_RATES or length <= head:
        return None
    return length, mpeg_id, sampling


def _aac(data, complete):
    pos = _id3(data, complete)
    first = _adts_frame(data, pos)
    if not first:
        raise Refused("aac", "it isn't AAC in ADTS (no valid ADTS header where one should be)")
    second = _adts_frame(data, pos + first[0])
    if not second or second[1:] != first[1:]:
        raise Refused("aac", "an ADTS frame isn't followed by a compatible frame header")
    return "aac"


# ---- Matroska and WebM ---------------------------------------------------------

EBML = 0x1A45DFA3
SEGMENT = 0x18538067
DOCTYPE = 0x4282
MAX_EBML_HEAD = 4096


def _vint(data, pos, keep_marker):
    """An EBML variable-length integer at pos: (value, length, all ones)"""
    if pos >= len(data):
        raise Refused("ebml", "an EBML number is cut short")
    first = data[pos]
    if first == 0:
        raise Refused("ebml", "an EBML number is longer than 8 bytes")
    length = 1
    while not first & (0x80 >> (length - 1)):
        length += 1
    if pos + length > len(data):
        raise Refused("ebml", "an EBML number is cut short")
    value = first if keep_marker else first & (0xFF >> length)
    for b in data[pos + 1:pos + length]:
        value = value << 8 | b
    ones = not keep_marker and value == (1 << (7 * length)) - 1
    return value, length, ones


def _ebml(data, complete):
    ident, n, _ = _vint(data, 0, True)
    if ident != EBML:
        raise Refused("ebml", "it doesn't start with an EBML header")
    size, m, unknown = _vint(data, n, False)
    if unknown or size > MAX_EBML_HEAD:
        raise Refused("ebml", "the EBML header's size isn't sane")
    start, end = n + m, n + m + size
    if end > len(data):
        raise Refused("ebml", "the EBML header is cut short")
    doctype = None
    pos = start
    while pos < end:
        cid, a, _ = _vint(data, pos, True)
        if a > 4:
            raise Refused("ebml", "an EBML element's id is longer than 4 bytes")
        csize, b, unknown = _vint(data, pos + a, False)
        if unknown or pos + a + b + csize > end:
            raise Refused("ebml", "an element of the EBML header runs past it")
        if cid == DOCTYPE:
            if doctype is not None:
                raise Refused("ebml", "the EBML header has two DocTypes")
            doctype = data[pos + a + b:pos + a + b + csize].rstrip(b"\0")
        pos += a + b + csize
    if doctype not in (b"matroska", b"webm"):
        raise Refused("ebml", "the EBML header's DocType isn't matroska or webm")
    if end < len(data):
        nxt, _, _ = _vint(data, end, True)
        if nxt != SEGMENT:
            raise Refused("ebml", "the EBML header isn't followed by a Segment")
    elif complete:
        raise Refused("ebml", "there's no Segment after the EBML header")
    return doctype.decode()


# ---- MPEG-TS, FLAC, Ogg ------------------------------------------------------------

def _ts(data, complete):
    if len(data) < 3 * 188:
        raise Refused("ts", "an MPEG-TS stream is shorter than three packets")
    for off in (0, 188, 376):
        if data[off] != 0x47:
            raise Refused("ts", "MPEG-TS packets don't start with 0x47 at 0, 188 and 376")
        if data[off + 3] & 0x30 == 0:
            raise Refused("ts", "an MPEG-TS packet has a reserved adaptation field setting")
    return "ts"


def _flac(data, complete):
    if not data.startswith(b"fLaC") or len(data) < 8:
        raise Refused("flac", "it isn't FLAC")
    if data[4] & 0x7F != 0 or int.from_bytes(data[5:8], "big") != 34:
        raise Refused("flac", "a FLAC stream starts with its STREAMINFO block")
    return "flac"


def _ogg(data, complete):
    if not data.startswith(b"OggS") or len(data) < 27:
        raise Refused("ogg", "it isn't Ogg")
    if data[4] != 0 or data[5] & ~0x07 or not data[5] & 0x02:
        raise Refused("ogg", "an Ogg stream starts with a version 0 first page")
    return "ogg"


# ---- which check, by how it was reached -----------------------------------------

def _mpeg_audio(data, complete, allowed):
    """MP3 or ADTS AAC (an ID3 tag first is fine): told apart by the layer
    bits of the header after the tag"""
    pos = _id3(data, complete)
    if pos + 2 <= len(data) and data[pos] == 0xFF:
        if data[pos + 1] & 0xF6 == 0xF0 and "aac" in allowed:
            return _aac(data, complete)
        if data[pos + 1] & 0xE0 == 0xE0 and "mp3" in allowed:
            return _mp3(data, complete)
    raise Refused("format", "it isn't media in a format the guide plays")


def check_media(cls, data, complete):
    """The format of media reached as cls ("direct", "segment" or "map"),
    from its first min(PROBE, size) bytes (complete: they're all of it);
    Refused if it isn't one the guide plays from there"""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise Refused("empty", "there's nothing in it")
    data = bytes(data[:PROBE])
    if cls == "map":
        return _fmp4_init(data, complete)
    if cls == "segment":
        if data[0] == 0x47:
            return _ts(data, complete)
        if data[4:8] in (b"styp", b"moof") or data[4:8] in SEGMENT_INDEX:
            return _fmp4_segment(data, complete)
        if data[:3] == b"ID3" or data[0] == 0xFF:
            return _mpeg_audio(data, complete, ("aac", "mp3"))   # packed audio
        if len(data) >= 8 and data[4:8].isalpha():
            raise Refused("fmp4", "an fMP4 segment starts with styp, an index (sidx and the like) or moof, not " + data[4:8].decode())
        raise Refused("format", "it isn't a segment in a format the guide plays")
    if cls == "direct":
        if data[4:8] == b"ftyp":
            return _mp4_direct(data, complete)
        if data[:4] == b"\x1a\x45\xdf\xa3":
            return _ebml(data, complete)
        if data[0] == 0x47:
            return _ts(data, complete)
        if data[:4] == b"fLaC":
            return _flac(data, complete)
        if data[:4] == b"OggS":
            return _ogg(data, complete)
        return _mpeg_audio(data, complete, ("aac", "mp3"))
    raise Refused("class", "not a kind of media the relay knows")


def check_key(data):
    """An AES-128 key, reached from a rewritten EXT-X-KEY: exactly 16 bytes"""
    if not isinstance(data, (bytes, bytearray)) or len(data) != 16:
        raise Refused("key", "a key is exactly 16 bytes (AES-128)")


# ---- HLS playlists (RFC 8216), fail-closed ------------------------------------------

# tags kept (checked, their URIs rewritten), and where they may be
MEDIA_TAGS = {"EXTINF", "EXT-X-TARGETDURATION", "EXT-X-MEDIA-SEQUENCE", "EXT-X-DISCONTINUITY-SEQUENCE",
              "EXT-X-DISCONTINUITY", "EXT-X-ENDLIST", "EXT-X-PLAYLIST-TYPE", "EXT-X-PROGRAM-DATE-TIME",
              "EXT-X-BYTERANGE", "EXT-X-GAP", "EXT-X-BITRATE", "EXT-X-KEY", "EXT-X-MAP"}
MASTER_TAGS = {"EXT-X-STREAM-INF", "EXT-X-MEDIA"}
BOTH_TAGS = {"EXT-X-VERSION", "EXT-X-INDEPENDENT-SEGMENTS", "EXT-X-START"}
# dropped with every URI they carry (safe to drop: players fall back)
# (EXT-X-IMAGE-STREAM-INF: Jellyfin 10.9+'s trickplay pictures, in a master)
STRIPPED_MASTER = {"EXT-X-SESSION-KEY", "EXT-X-SESSION-DATA", "EXT-X-I-FRAME-STREAM-INF", "EXT-X-IMAGE-STREAM-INF"}
STRIPPED_MEDIA = {"EXT-X-PART", "EXT-X-PART-INF", "EXT-X-PRELOAD-HINT", "EXT-X-RENDITION-REPORT",
                  "EXT-X-SERVER-CONTROL", "EXT-X-SKIP"}
ONCE = {"EXT-X-VERSION", "EXT-X-TARGETDURATION", "EXT-X-MEDIA-SEQUENCE", "EXT-X-DISCONTINUITY-SEQUENCE",
        "EXT-X-PLAYLIST-TYPE", "EXT-X-ENDLIST", "EXT-X-INDEPENDENT-SEGMENTS", "EXT-X-START"}
NO_VALUE = {"EXT-X-DISCONTINUITY", "EXT-X-ENDLIST", "EXT-X-INDEPENDENT-SEGMENTS", "EXT-X-GAP"}

# the attributes each attribute-list tag passes on (RFC 8216 and its
# successor draft); an unknown one is dropped, or rejects the playlist if it
# could carry a URI
ATTRS = {
    "EXT-X-KEY": {"METHOD", "URI", "IV", "KEYFORMAT", "KEYFORMATVERSIONS"},
    "EXT-X-MAP": {"URI", "BYTERANGE"},
    "EXT-X-MEDIA": {"TYPE", "URI", "GROUP-ID", "LANGUAGE", "ASSOC-LANGUAGE", "NAME", "STABLE-RENDITION-ID",
                    "DEFAULT", "AUTOSELECT", "FORCED", "INSTREAM-ID", "BIT-DEPTH", "SAMPLE-RATE",
                    "CHARACTERISTICS", "CHANNELS"},
    "EXT-X-STREAM-INF": {"BANDWIDTH", "AVERAGE-BANDWIDTH", "SCORE", "CODECS", "SUPPLEMENTAL-CODECS",
                         "RESOLUTION", "FRAME-RATE", "HDCP-LEVEL", "ALLOWED-CPC", "VIDEO-RANGE",
                         "REQ-VIDEO-LAYOUT", "STABLE-VARIANT-ID", "AUDIO", "VIDEO", "SUBTITLES",
                         "CLOSED-CAPTIONS", "PATHWAY-ID", "PROGRAM-ID"},
    "EXT-X-START": {"TIME-OFFSET", "PRECISE"},
}

ATTR_RE = re.compile(r'([A-Z0-9-]+)=("[^"\r\n]*"|[^",\s]+)(,|$)')
INT_RE = re.compile(r"^[0-9]{1,20}\Z")
FLOAT_RE = re.compile(r"^[0-9]{1,20}(\.[0-9]{1,20})?\Z")
SFLOAT_RE = re.compile(r"^-?[0-9]{1,20}(\.[0-9]{1,20})?\Z")
HEX_RE = re.compile(r"^0[xX][0-9A-Fa-f]{1,64}\Z")
RANGE_RE = re.compile(r"^[0-9]{1,20}(@[0-9]{1,20})?\Z")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?(Z|[+-][0-9]{2}:?[0-9]{2})\Z")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _bad(text):
    raise Refused("playlist", text)


def _attrs(tag, value):
    """An attribute list (RFC 8216 4.2), strictly: an ordered list of
    [name, value, quoted]"""
    out, names, pos = [], set(), 0
    while pos < len(value):
        m = ATTR_RE.match(value, pos)
        if not m:
            _bad(tag + " has a malformed attribute list")
        name, raw = m.group(1), m.group(2)
        if name in names:
            _bad(tag + " has " + name + " twice")
        names.add(name)
        quoted = raw.startswith('"')
        val = raw[1:-1] if quoted else raw
        if name not in ATTRS[tag]:
            # one RFC 8216 doesn't define: dropped, unless it could be a link
            # (its name says URI, or its value has a scheme, a slash or a
            # backslash), which nothing here would rewrite: then refused
            if "URI" in name or ":" in val or "/" in val or "\\" in val:
                _bad(tag + " has an attribute (" + name + ") that could be a link the guide doesn't rewrite")
        else:
            out.append([name, val, quoted])
        pos = m.end()
        if m.group(3) == "," and pos == len(value):
            _bad(tag + " has a malformed attribute list")
    if not out:
        _bad(tag + " has no attributes")
    return out


def _get(attrs, name):
    for a in attrs:
        if a[0] == name:
            return a
    return None


def _need(attrs, name, tag, quoted=None, pattern=None, choices=None):
    a = _get(attrs, name)
    if a is None:
        _bad(tag + " has no " + name)
    _check(a, tag, quoted, pattern, choices)
    return a


def _check(a, tag, quoted=None, pattern=None, choices=None):
    if a is None:
        return
    if quoted is not None and a[2] != quoted:
        _bad(tag + "'s " + a[0] + " is " + ("not " if quoted else "") + "meant to be quoted")
    if pattern is not None and not pattern.match(a[1]):
        _bad(tag + "'s " + a[0] + " isn't well formed")
    if choices is not None and a[1] not in choices:
        _bad(tag + "'s " + a[0] + " (" + a[1][:40] + ") isn't one the guide passes")


def _uri(raw, final_url):
    """A URI from a playlist, resolved against the playlist's final URL:
    http or https only"""
    if not raw or CTRL_RE.search(raw) or any(c.isspace() for c in raw) or '"' in raw:
        _bad("a URI in the playlist has spaces, quotes or control characters")
    url = urllib.parse.urljoin(final_url, raw)
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        _bad("a URI in the playlist isn't http or https")
    return url


def _serialize(tag, attrs):
    return "#" + tag + ":" + ",".join(n + "=" + ('"' + v + '"' if q else v) for n, v, q in attrs)


def _check_stream_inf(attrs):
    tag = "EXT-X-STREAM-INF"
    _need(attrs, "BANDWIDTH", tag, False, INT_RE)
    _check(_get(attrs, "AVERAGE-BANDWIDTH"), tag, False, INT_RE)
    _check(_get(attrs, "SCORE"), tag, False, FLOAT_RE)
    _check(_get(attrs, "RESOLUTION"), tag, False, re.compile(r"^[0-9]{1,6}x[0-9]{1,6}\Z"))
    _check(_get(attrs, "FRAME-RATE"), tag, False, FLOAT_RE)
    _check(_get(attrs, "PROGRAM-ID"), tag, False, INT_RE)
    for name in ("CODECS", "SUPPLEMENTAL-CODECS", "STABLE-VARIANT-ID", "AUDIO", "VIDEO", "SUBTITLES", "PATHWAY-ID",
                 "ALLOWED-CPC", "REQ-VIDEO-LAYOUT"):
        _check(_get(attrs, name), tag, True)
    for name in ("HDCP-LEVEL", "VIDEO-RANGE"):
        _check(_get(attrs, name), tag, False)
    cc = _get(attrs, "CLOSED-CAPTIONS")
    if cc is not None and not cc[2] and cc[1] != "NONE":
        _bad(tag + "'s CLOSED-CAPTIONS is a quoted group or NONE")


def _check_media(attrs):
    tag = "EXT-X-MEDIA"
    kind = _need(attrs, "TYPE", tag, False, choices=("AUDIO", "VIDEO", "SUBTITLES", "CLOSED-CAPTIONS"))[1]
    _need(attrs, "GROUP-ID", tag, True)
    _need(attrs, "NAME", tag, True)
    for name in ("LANGUAGE", "ASSOC-LANGUAGE", "STABLE-RENDITION-ID", "INSTREAM-ID", "CHARACTERISTICS", "CHANNELS"):
        _check(_get(attrs, name), tag, True)
    for name in ("DEFAULT", "AUTOSELECT", "FORCED"):
        _check(_get(attrs, name), tag, False, choices=("YES", "NO"))
    _check(_get(attrs, "BIT-DEPTH"), tag, False, INT_RE)
    _check(_get(attrs, "SAMPLE-RATE"), tag, False, INT_RE)
    uri = _get(attrs, "URI")
    _check(uri, tag, True)
    if kind == "CLOSED-CAPTIONS":
        if uri is not None:
            _bad("a CLOSED-CAPTIONS rendition has a URI (RFC 8216 4.3.4.1 forbids one)")
        _need(attrs, "INSTREAM-ID", tag, True)
    elif kind == "SUBTITLES" and uri is None:
        _bad("a SUBTITLES rendition has no URI")
    return kind


def _check_key(attrs):
    tag = "EXT-X-KEY"
    method = _need(attrs, "METHOD", tag, False)[1]
    if method not in ("NONE", "AES-128"):
        _bad("the playlist is encrypted with " + method[:20] + ", which the guide doesn't play")
    if method == "NONE":
        if len(attrs) != 1:
            _bad("an EXT-X-KEY with METHOD=NONE has other attributes")
        return
    _need(attrs, "URI", tag, True)
    _check(_get(attrs, "IV"), tag, False, re.compile(r"^0[xX][0-9A-Fa-f]{32}\Z"))
    kf = _get(attrs, "KEYFORMAT")
    _check(kf, tag, True, choices=("identity",))
    _check(_get(attrs, "KEYFORMATVERSIONS"), tag, True, choices=("1",))


def _value_ok(tag, value):
    if tag in NO_VALUE:
        if value is not None:
            _bad(tag + " takes no value")
        return
    if value is None:
        _bad(tag + " needs a value")
    if tag in ("EXT-X-VERSION", "EXT-X-TARGETDURATION", "EXT-X-MEDIA-SEQUENCE", "EXT-X-DISCONTINUITY-SEQUENCE",
               "EXT-X-BITRATE"):
        if not INT_RE.match(value):
            _bad(tag + " isn't a whole number")
    elif tag == "EXTINF":
        duration = value.split(",", 1)[0]
        if not FLOAT_RE.match(duration):
            _bad("EXTINF's duration isn't a number")
    elif tag == "EXT-X-PLAYLIST-TYPE":
        if value not in ("EVENT", "VOD"):
            _bad("EXT-X-PLAYLIST-TYPE is EVENT or VOD")
    elif tag == "EXT-X-PROGRAM-DATE-TIME":
        if not DATE_RE.match(value):
            _bad("EXT-X-PROGRAM-DATE-TIME isn't a date and time")
    elif tag == "EXT-X-BYTERANGE":
        if not RANGE_RE.match(value):
            _bad("EXT-X-BYTERANGE isn't a byte range")


def rewrite_playlist(data, final_url, depth, register):
    """An HLS playlist, checked fail-closed and rewritten: every URI in it
    resolved against final_url (where it was fetched from, after redirects)
    and replaced by register(url, kind), kind "playlist", "segment", "map"
    or "key" (register raises Refused for a URL outside the origin rules).
    Nothing is registered unless the whole playlist passes. Returns UTF-8
    bytes with LF line endings."""
    if not isinstance(data, (bytes, bytearray)):
        _bad("the playlist isn't bytes")
    if len(data) > MAX_PLAYLIST:
        _bad("the playlist is bigger than 1 MB")
    if depth < 0 or depth > MAX_DEPTH:
        _bad("playlists nest two deep at most")
    if urllib.parse.urlsplit(str(final_url)).scheme.lower() not in ("http", "https"):
        _bad("the playlist didn't come from an http or https URL")
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError:
        _bad("the playlist isn't UTF-8")
    if text.startswith("﻿"):
        text = text[1:]
    lines = []
    for raw in text.split("\n"):
        if raw.endswith("\r"):
            raw = raw[:-1]
        raw = raw.rstrip(" \t")
        if CTRL_RE.search(raw.replace("\t", " ")):
            _bad("the playlist has control characters in it")
        lines.append(raw)
    while lines and not lines[0]:
        lines.pop(0)
    if not lines or lines[0] != "#EXTM3U":
        _bad("it doesn't start with #EXTM3U")

    # pass 1: every line checked, the output planned; nothing registered yet
    items = []           # ("line", text) | ("tag", tag, attrs, kind, url) | ("uri", url, kind)
    master = media = False
    seen = set()
    subtitle_groups = set()
    pending_inf = False      # an EXTINF waiting for its URI
    pending_stream = False   # an EXT-X-STREAM-INF waiting for its URI
    stream_infs = []
    uris = 0
    for line in lines[1:]:
        if not line:
            continue
        if line.startswith("#EXT"):
            tag, colon, value = line[1:].partition(":")
            value = value if colon else None
            if tag in STRIPPED_MASTER:
                master = True
                continue
            if tag in STRIPPED_MEDIA:
                media = True
                continue
            if tag not in MEDIA_TAGS | MASTER_TAGS | BOTH_TAGS:
                _bad("the playlist has a tag (" + tag[:40] + ") the guide doesn't pass")
            if tag in ONCE:
                if tag in seen:
                    _bad("the playlist has " + tag + " twice")
                seen.add(tag)
            if tag in MEDIA_TAGS:
                media = True
            if tag in MASTER_TAGS:
                master = True
            if pending_stream:
                _bad("an EXT-X-STREAM-INF isn't followed by its URI")
            if tag in ATTRS:
                if value is None:
                    _bad(tag + " needs attributes")
                attrs = _attrs(tag, value)
                if tag == "EXT-X-STREAM-INF":
                    _check_stream_inf(attrs)
                    pending_stream = True
                    stream_infs.append(attrs)
                    items.append(("tag", tag, attrs, None, None))
                elif tag == "EXT-X-MEDIA":
                    kind = _check_media(attrs)
                    if kind == "SUBTITLES":
                        subtitle_groups.add(_get(attrs, "GROUP-ID")[1])
                        continue        # stripped, with its STREAM-INF references below
                    uri = _get(attrs, "URI")
                    if uri:
                        uris += 1
                    items.append(("tag", tag, attrs, "playlist" if uri else None, _uri(uri[1], final_url) if uri else None))
                elif tag == "EXT-X-KEY":
                    _check_key(attrs)
                    uri = _get(attrs, "URI")
                    if uri:
                        uris += 1
                    items.append(("tag", tag, attrs, "key" if uri else None, _uri(uri[1], final_url) if uri else None))
                elif tag == "EXT-X-MAP":
                    uri = _need(attrs, "URI", tag, True)
                    _check(_get(attrs, "BYTERANGE"), tag, True, RANGE_RE)
                    uris += 1
                    items.append(("tag", tag, attrs, "map", _uri(uri[1], final_url)))
                else:   # EXT-X-START
                    _need(attrs, "TIME-OFFSET", tag, False, SFLOAT_RE)
                    _check(_get(attrs, "PRECISE"), tag, False, choices=("YES", "NO"))
                    items.append(("tag", tag, attrs, None, None))
                continue
            _value_ok(tag, value)
            if tag == "EXTINF":
                if pending_inf:
                    _bad("an EXTINF isn't followed by its segment")
                pending_inf = True
            items.append(("line", line))
            continue
        if line.startswith("#"):
            continue              # a plain comment: dropped
        # a URI line
        if pending_stream:
            items.append(("uri", _uri(line, final_url), "playlist"))
            pending_stream = False
        elif pending_inf:
            items.append(("uri", _uri(line, final_url), "segment"))
            pending_inf = False
        else:
            _bad("the playlist has a URI that no EXTINF or EXT-X-STREAM-INF introduces")
        uris += 1
        if uris > MAX_URIS:
            _bad("the playlist has more than 20,000 URIs")
    if uris > MAX_URIS:
        _bad("the playlist has more than 20,000 URIs")
    if master and media:
        _bad("the playlist mixes master and media playlist tags")
    if pending_inf or pending_stream:
        _bad("the playlist ends before a segment's or variant's URI")
    if master:
        if depth > 0:
            _bad("a master playlist can't be inside another playlist")
        if not stream_infs:
            _bad("the master playlist has no variants")
        for attrs in stream_infs:
            sub = _get(attrs, "SUBTITLES")
            if sub is not None:
                if sub[1] not in subtitle_groups:
                    _bad("an EXT-X-STREAM-INF names a SUBTITLES group that isn't there")
                attrs.remove(sub)
    elif media:
        if "EXT-X-TARGETDURATION" not in seen:
            _bad("the media playlist has no EXT-X-TARGETDURATION")
    else:
        _bad("the playlist has no variants and no segments")

    # pass 2: resolve and register every URI, in order
    out = ["#EXTM3U"]
    for item in items:
        if item[0] == "line":
            out.append(item[1])
        elif item[0] == "uri":
            out.append(_relay(register(item[1], item[2])))
        else:
            _, tag, attrs, kind, url = item
            if kind:
                a = _get(attrs, "URI")
                a[1] = _relay(register(url, kind))
                a[2] = True
            out.append(_serialize(tag, attrs))
    return ("\n".join(out) + "\n").encode("utf-8")


def _relay(path):
    if not isinstance(path, str) or not path or CTRL_RE.search(path) or '"' in path or any(c.isspace() for c in path):
        raise Refused("register", "the relay gave a path a playlist can't hold")
    return path
