#!/usr/bin/env python3
"""lib/appmedia.py: the media relay's structure checks and its fail-closed
HLS rewrite. Positive and negative
fixtures for every format, built here; with /usr/bin/ffmpeg, real files too.

    /usr/bin/python3 tests/appmedia.test.py
"""

import os
import struct
import subprocess
import tempfile
import unittest
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))
M = SourceFileLoader("appmedia", os.path.join(HERE, "..", "lib", "appmedia.py")).load_module()
Refused = M.Refused
FFMPEG = "/usr/bin/ffmpeg"


# ---- fixtures ------------------------------------------------------------------

def box(kind, payload=b""):
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


FTYP = box(b"ftyp", b"isom" + b"\0\0\2\0" + b"isomiso2avc1mp41")
MOOV = box(b"moov", box(b"mvhd", b"\0" * 100) + box(b"trak", box(b"tkhd", b"\0" * 84)))
MDAT = box(b"mdat", b"\0" * 1000)
FREE = box(b"free")
STYP = box(b"styp", b"msdh\0\0\0\0msdhmsix")
SIDX = box(b"sidx", b"\0" * 44)
MOOF = box(b"moof", box(b"mfhd", b"\0" * 8) + box(b"traf", box(b"tfhd", b"\0" * 8)))


def mp3_header(kbps_index=9, rate_index=0, pad=0, layer=1, version=3):
    h = 0x7FF << 21 | version << 19 | layer << 17 | 1 << 16 | kbps_index << 12 | rate_index << 10 | pad << 9
    return struct.pack(">I", h)


def mp3_frames(n=2, rate_index=0):
    # MPEG-1 Layer III, 128 kbps, 44.1 kHz: 144 * 128000 / 44100 = 417 bytes
    size = 144 * 128000 // [44100, 48000, 32000][rate_index]
    frame = mp3_header(rate_index=rate_index)
    return b"".join(frame + b"\0" * (size - 4) for _ in range(n))


def id3(payload=b"\0" * 20, major=4):
    size = len(payload)
    safe = bytes([(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F])
    return b"ID3" + bytes([major, 0, 0]) + safe + payload


def adts(length=100, sampling=4):
    b = bytearray(7)
    b[0], b[1] = 0xFF, 0xF1                      # MPEG-4, layer 00, no CRC
    b[2] = 1 << 6 | sampling << 2                 # AAC LC
    b[3] = 2 << 6 | (length >> 11) & 3            # 2 channels
    b[4] = (length >> 3) & 0xFF
    b[5] = (length & 7) << 5 | 0x1F
    b[6] = 0xFC
    return bytes(b) + b"\0" * (length - 7)


def ebml_el(ident, payload):
    assert len(payload) < 127
    return ident + bytes([0x80 | len(payload)]) + payload


def ebml(doctype=b"webm", then=b"\x18\x53\x80\x67\x01\xff\xff\xff\xff\xff\xff\xff" + b"\0" * 16):
    kids = (ebml_el(b"\x42\x86", b"\x01") + ebml_el(b"\x42\xf7", b"\x01") + ebml_el(b"\x42\xf2", b"\x04") +
            ebml_el(b"\x42\xf3", b"\x08") + ebml_el(b"\x42\x82", doctype) + ebml_el(b"\x42\x87", b"\x02") +
            ebml_el(b"\x42\x85", b"\x02"))
    return ebml_el(b"\x1a\x45\xdf\xa3", kids) + then


def ts(packets=3):
    pkt = b"\x47\x40\x00\x10" + b"\xff" * 184
    return pkt * packets


FLAC = b"fLaC" + b"\x00\x00\x00\x22" + b"\0" * 34 + b"\x84\x00\x00\x08" + b"\0" * 8
OGG = b"OggS\x00\x02" + b"\0" * 21 + b"\x01\x1e" + b"\0" * 30


class Recorder:
    def __init__(self, refuse=None):
        self.calls = []
        self.refuse = refuse

    def __call__(self, url, kind):
        if self.refuse and self.refuse(url, kind):
            raise Refused("origin", "outside the app's origins")
        self.calls.append((url, kind))
        return "/r/%d/x" % len(self.calls)


def rewrite(text, url="https://media.example/p/index.m3u8", depth=0, reg=None):
    reg = reg or Recorder()
    out = M.rewrite_playlist(text.encode() if isinstance(text, str) else text, url, depth, reg)
    return out.decode(), reg


# ---- structure checks -------------------------------------------------------------

class IsoBmff(unittest.TestCase):
    def test_plain_layout(self):          # FFmpeg's default: ftyp free mdat moov
        self.assertEqual(M.check_media("direct", FTYP + FREE + MDAT + MOOV, True), "mp4")

    def test_faststart_layout(self):      # ftyp moov free mdat
        self.assertEqual(M.check_media("direct", FTYP + MOOV + FREE + MDAT, True), "mp4")

    def test_mdat_past_the_probe(self):
        big = struct.pack(">I4s", 50_000_000, b"mdat") + b"\0" * (M.PROBE - len(FTYP) - len(FREE) - 8)
        self.assertEqual(M.check_media("direct", FTYP + FREE + big, False), "mp4")

    def test_largesize_mdat(self):
        big = struct.pack(">I4sQ", 1, b"mdat", 1 << 33) + b"\0" * 100
        self.assertEqual(M.check_media("direct", FTYP + MOOV + big, False), "mp4")

    def test_bad(self):
        cases = {
            "moov first": MOOV + FTYP + MDAT,
            "unknown top-level box": FTYP + box(b"junk", b"1234") + MOOV + MDAT,
            "moov without mvhd": FTYP + box(b"moov", box(b"trak")) + MDAT,
            "no moov in a complete file": FTYP + FREE + MDAT,
            "box size 4": FTYP + struct.pack(">I4s", 4, b"free") + MOOV,
            "box past the end": FTYP + MOOV + struct.pack(">I4s", 5000, b"mdat") + b"\0" * 10,
            "unprintable type": FTYP + struct.pack(">I4s", 8, b"\x00\x01ab") + MOOV,
            "two moovs": FTYP + MOOV + MOOV + MDAT,
            "ftyp with a ragged size": box(b"ftyp", b"isom\0\0\0\0ab") + MOOV,
            "moov children overflow": FTYP + struct.pack(">I4s", 16, b"moov") + struct.pack(">I4s", 100, b"mvhd") + MDAT,
        }
        for name, data in cases.items():
            with self.subTest(name), self.assertRaises(Refused):
                M.check_media("direct", data, True)

    def test_fmp4_init(self):
        self.assertEqual(M.check_media("map", FTYP + MOOV, True), "fmp4-init")
        for name, data in {"free between": FTYP + FREE + MOOV, "moov first": MOOV, "ftyp only": FTYP,
                           "mdat after": FTYP + MOOV + MDAT, "a segment": STYP + MOOF + MDAT}.items():
            with self.subTest(name), self.assertRaises(Refused):
                M.check_media("map", data, True)

    def test_fmp4_segment(self):
        for name, data in {"styp moof mdat": STYP + MOOF + MDAT, "moof mdat": MOOF + MDAT,
                           "FFmpeg's styp sidx sidx moof mdat": STYP + SIDX + SIDX + MOOF + MDAT,
                           "two pairs": MOOF + MDAT + MOOF + MDAT}.items():
            with self.subTest(name):
                self.assertEqual(M.check_media("segment", data, True), "fmp4-segment")

    def test_fmp4_segment_led_by_its_index(self):
        """FFmpeg's single-file fMP4 segments: sidx, moof, mdat (no styp)"""
        mfhd = struct.pack(">I4s", 16, b"mfhd") + b"\0" * 8
        moof = struct.pack(">I4s", 8 + len(mfhd), b"moof") + mfhd
        mdat = struct.pack(">I4s", 108, b"mdat") + b"\0" * 100
        sidx = struct.pack(">I4s", 52, b"sidx") + b"\0" * 44
        self.assertEqual(M.check_media("segment", sidx + moof + mdat, True), "fmp4-segment")
        free = struct.pack(">I4s", 16, b"free") + b"\0" * 8
        with self.assertRaises(M.Refused):
            M.check_media("segment", free + moof + mdat, True)   # any other leading box: refused

    def test_fmp4_index_past_the_probe(self):
        """an index running past the probe, no moof seen: refused (it hasn't shown it's a segment)"""
        styp = struct.pack(">I4s", 16, b"styp") + b"msdh" + b"\0\0\0\0"
        sidx = struct.pack(">I4s", 100000, b"sidx") + b"\0" * 100
        data = (styp + sidx + b"\0" * M.PROBE)[:M.PROBE]
        with self.assertRaises(M.Refused):
            M.check_media("segment", data, False)

    def test_fmp4_segment_bad(self):
        cases = {
            "leading free": FREE + MOOF + MDAT,
            "leading unknown box": box(b"junk") + MOOF + MDAT,
            "leading free": box(b"free", b"\0" * 8) + MOOF + MDAT,
            "moof then moof": STYP + MOOF + MOOF + MDAT,
            "styp then mdat": STYP + MDAT,
            "styp alone": STYP,
            "moof without mfhd": box(b"moof", box(b"traf")) + MDAT,
            "a whole mp4": FTYP + MOOV + MDAT,
            "stray mdat": MOOF + MDAT + MDAT,
            "free between styp and moof": STYP + FREE + MOOF + MDAT,
        }
        for name, data in cases.items():
            with self.subTest(name), self.assertRaises(Refused):
                M.check_media("segment", data, True)


class MpegAudio(unittest.TestCase):
    def test_mp3(self):
        self.assertEqual(M.check_media("direct", mp3_frames(2), True), "mp3")
        self.assertEqual(M.check_media("direct", id3() + mp3_frames(3), True), "mp3")
        self.assertEqual(M.check_media("direct", id3(major=3) + mp3_frames(2), True), "mp3")
        self.assertEqual(M.check_media("segment", id3() + mp3_frames(2), True), "mp3")

    def test_mp3_bad(self):
        size = 417
        cases = {
            "ID3 then junk": id3() + b"\x12\x34" * 500,
            "one plausible header then junk": mp3_header() + b"\x55" * 2000,
            "Layer II": (mp3_header(layer=2) + b"\0" * (size - 4)) * 2,
            "free-format bitrate": (mp3_header(kbps_index=0) + b"\0" * 400) * 2,
            "reserved version": (mp3_header(version=1) + b"\0" * 400) * 2,
            "a second frame at another sample rate": mp3_frames(1) + mp3_header(rate_index=1) + b"\0" * 400,
            "ID3 bigger than the probe": id3(b"\0" * (M.PROBE + 10)) + mp3_frames(2),
            "ID3 with a size that isn't synchsafe": b"ID3\x04\x00\x00\x00\x00\x00\x8a" + mp3_frames(2),
        }
        for name, data in cases.items():
            with self.subTest(name), self.assertRaises(Refused):
                M.check_media("direct", data[:M.PROBE], len(data) <= M.PROBE)

    def test_aac(self):
        self.assertEqual(M.check_media("direct", adts() + adts(120), True), "aac")
        self.assertEqual(M.check_media("segment", id3() + adts() + adts(), True), "aac")   # HLS packed audio

    def test_aac_bad(self):
        cases = {
            "one frame then junk": adts() + b"\x11" * 200,
            "frame length shorter than its header": adts(100)[:3] + b"\x00\x00\x1f\xfc" + b"\0" * 200,
            "sampling index 13": adts(sampling=13) * 2,
            "second frame at another rate": adts() + adts(sampling=3),
            "layer bits set": bytes([0xFF, 0xF3]) + adts()[2:] + adts(),
        }
        for name, data in cases.items():
            with self.subTest(name), self.assertRaises(Refused):
                M.check_media("direct", data, True)


class Containers(unittest.TestCase):
    def test_matroska_webm(self):
        self.assertEqual(M.check_media("direct", ebml(b"webm"), False), "webm")
        self.assertEqual(M.check_media("direct", ebml(b"matroska"), False), "matroska")
        self.assertEqual(M.check_media("direct", ebml(b"webm\0\0"), False), "webm")

    def test_ebml_bad(self):
        cases = {
            "another DocType": ebml(b"mp4"),
            "DocType prefix": ebml(b"matroskax"),
            "not followed by a Segment": ebml(b"webm", then=b"\x1f\x43\xb6\x75\x80"),
            "no Segment in a complete file": ebml(b"webm", then=b""),
            "unknown-size header": b"\x1a\x45\xdf\xa3\xff" + b"\0" * 40,
            "child runs past the header": b"\x1a\x45\xdf\xa3\x84\x42\x82\x88webm" + b"\0" * 20,
        }
        for name, data in cases.items():
            with self.subTest(name), self.assertRaises(Refused):
                M.check_media("direct", data, name == "no Segment in a complete file")

    def test_ts(self):
        self.assertEqual(M.check_media("direct", ts(3), True), "ts")
        self.assertEqual(M.check_media("segment", ts(5), True), "ts")
        for name, data in {"two packets": ts(2), "third sync wrong": ts(2) + b"\x48" + ts(1)[1:],
                           "reserved adaptation field": b"\x47\x40\x00\x00" + b"\xff" * 184 + ts(2)}.items():
            with self.subTest(name), self.assertRaises(Refused):
                M.check_media("segment", data, True)

    def test_flac_ogg(self):
        self.assertEqual(M.check_media("direct", FLAC, True), "flac")
        self.assertEqual(M.check_media("direct", OGG, True), "ogg")
        for name, data in {"FLAC without STREAMINFO first": b"fLaC\x04\x00\x00\x08" + b"\0" * 40,
                           "Ogg version 1": b"OggS\x01\x02" + b"\0" * 40,
                           "Ogg page that isn't first": b"OggS\x00\x00" + b"\0" * 40}.items():
            with self.subTest(name), self.assertRaises(Refused):
                M.check_media("direct", data, True)

    def test_not_allowed_where_reached(self):
        with self.assertRaises(Refused):
            M.check_media("segment", FLAC, True)       # FLAC isn't an HLS segment format
        with self.assertRaises(Refused):
            M.check_media("map", ts(3), True)
        with self.assertRaises(Refused):
            M.check_media("direct", STYP + MOOF + MDAT, True)
        for junk in (b"<html><body>", b"\x89PNG\r\n\x1a\n" + b"\0" * 40, b"#EXTM3U\n", b"", b"GIF89a" + b"\0" * 40):
            with self.subTest(junk[:10]), self.assertRaises(Refused):
                M.check_media("direct", junk, True)
        with self.assertRaises(Refused):
            M.check_media("other", ts(3), True)

    def test_key(self):
        M.check_key(b"k" * 16)
        for n in (0, 15, 17, 32):
            with self.subTest(n), self.assertRaises(Refused):
                M.check_key(b"k" * n)

    def test_sniff(self):
        self.assertEqual(M.sniff(b"#EXTM3U\n#EXT-X-VERSION:3\n"), "playlist")
        self.assertEqual(M.sniff(b"\xef\xbb\xbf#EXTM3U\r\n"), "playlist")
        self.assertEqual(M.sniff(b"#EXTM3U"), "playlist")
        for data in (FTYP, b" #EXTM3U\n", b"#EXTM3UX\n", b"#EXTINF:1\n", b""):
            with self.subTest(data[:10]):
                self.assertEqual(M.sniff(data), "media")


# ---- HLS ----------------------------------------------------------------------------

MASTER = """#EXTM3U
#EXT-X-VERSION:6
#EXT-X-INDEPENDENT-SEGMENTS
# a comment
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",LANGUAGE="en",DEFAULT=NO,URI="subs/en.m3u8"
#EXT-X-MEDIA:TYPE=CLOSED-CAPTIONS,GROUP-ID="cc",NAME="CC1",INSTREAM-ID="CC1"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="Main",DEFAULT=YES,AUTOSELECT=YES,URI="audio/main.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=1280000,RESOLUTION=640x360,CODECS="avc1.4d401e,mp4a.40.2",AUDIO="aud",SUBTITLES="subs",CLOSED-CAPTIONS="cc"
video/360.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2560000,SUBTITLES="subs",CLOSED-CAPTIONS=NONE
video/720.m3u8
"""

MEDIA = """#EXTM3U
#EXT-X-VERSION:7
#EXT-X-TARGETDURATION:6
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-PLAYLIST-TYPE:VOD
#EXT-X-MAP:URI="init.mp4",BYTERANGE="720@0"
#EXT-X-KEY:METHOD=AES-128,URI="https://keys.example/k1",IV=0x00000000000000000000000000000001,KEYFORMAT="identity",KEYFORMATVERSIONS="1"
#EXT-X-PROGRAM-DATE-TIME:2026-10-12T01:00:00.000Z
#EXTINF:6.0,first
seg1.m4s
#EXT-X-DISCONTINUITY
#EXT-X-BYTERANGE:1000@0
#EXTINF:6,
seg2.m4s
#EXT-X-KEY:METHOD=NONE
#EXTINF:5.5,
../other/seg3.m4s
#EXT-X-ENDLIST
"""


class Hls(unittest.TestCase):
    def test_master_subtitles_stripped_captions_kept(self):
        out, reg = rewrite(MASTER)
        self.assertNotIn("SUBTITLES", out)
        self.assertNotIn("subs", out)
        self.assertIn('#EXT-X-MEDIA:TYPE=CLOSED-CAPTIONS,GROUP-ID="cc",NAME="CC1",INSTREAM-ID="CC1"', out)
        self.assertIn('CLOSED-CAPTIONS="cc"', out)
        self.assertIn("CLOSED-CAPTIONS=NONE", out)
        self.assertNotIn("# a comment", out)
        self.assertEqual([k for _, k in reg.calls], ["playlist"] * 3)
        self.assertEqual([u for u, _ in reg.calls], ["https://media.example/p/audio/main.m3u8",
                                                     "https://media.example/p/video/360.m3u8",
                                                     "https://media.example/p/video/720.m3u8"])
        self.assertTrue(out.startswith("#EXTM3U\n") and out.endswith("\n") and "\r" not in out)
        self.assertIn('URI="/r/1/x"', out)
        self.assertIn("\n/r/2/x\n", out)

    def test_unknown_attributes(self):
        """One RFC 8216 doesn't define (Mux's test streams put NAME on
        EXT-X-STREAM-INF) is dropped; one that could be a link is refused"""
        m = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000,NAME="1080p",X-FOO=12\nv.m3u8\n'
        out, reg = rewrite(m)
        self.assertIn("#EXT-X-STREAM-INF:BANDWIDTH=1000\n", out)
        self.assertNotIn("1080p", out)
        for bad in ('NAME="https://evil.example/x"', 'X-THUMB="/thumbs/a.jpg"', "X-ICON-URI=abc"):
            with self.assertRaises(M.Refused):
                rewrite('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000,' + bad + '\nv.m3u8\n')

    def test_media_rewritten(self):
        out, reg = rewrite(MEDIA, url="https://cdn.example/a/b/index.m3u8?token=1")
        self.assertEqual(reg.calls, [("https://cdn.example/a/b/init.mp4", "map"), ("https://keys.example/k1", "key"),
                                     ("https://cdn.example/a/b/seg1.m4s", "segment"),
                                     ("https://cdn.example/a/b/seg2.m4s", "segment"),
                                     ("https://cdn.example/a/other/seg3.m4s", "segment")])
        self.assertIn('#EXT-X-MAP:URI="/r/1/x",BYTERANGE="720@0"', out)
        self.assertIn('#EXT-X-KEY:METHOD=AES-128,URI="/r/2/x",IV=0x00000000000000000000000000000001,KEYFORMAT="identity",KEYFORMATVERSIONS="1"', out)
        self.assertIn("#EXT-X-KEY:METHOD=NONE", out)
        self.assertIn("#EXT-X-BYTERANGE:1000@0", out)
        self.assertNotIn("seg1", out)

    def test_relative_against_final_url(self):
        # fetched from https://origin.example/play, redirected to the CDN: the CDN is the base
        out, reg = rewrite("#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\nseg.ts\n#EXTINF:4,\n/abs.ts\n#EXTINF:4,\n//other.example/x.ts\n",
                           url="https://cdn.example/live/x/index.m3u8")
        self.assertEqual([u for u, _ in reg.calls], ["https://cdn.example/live/x/seg.ts", "https://cdn.example/abs.ts",
                                                     "https://other.example/x.ts"])

    def test_crlf_bom_comments(self):
        text = "﻿#EXTM3U\r\n#EXT-X-TARGETDURATION:4\r\n# just a note\r\n\r\n#EXTINF:4,\r\nseg.ts\r\n"
        out, reg = rewrite(text)
        self.assertEqual(out, "#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\n/r/1/x\n")

    def test_stripped_tags(self):
        master = MASTER.replace("#EXT-X-INDEPENDENT-SEGMENTS\n", '#EXT-X-INDEPENDENT-SEGMENTS\n'
                                '#EXT-X-SESSION-KEY:METHOD=AES-128,URI="https://evil.example/k"\n'
                                '#EXT-X-SESSION-DATA:DATA-ID="com.x",URI="https://evil.example/d.json"\n'
                                '#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=1000,URI="https://evil.example/if.m3u8"\n'
                                # what Jellyfin 10.9+ adds for an item with trickplay pictures
                                '#EXT-X-IMAGE-STREAM-INF:BANDWIDTH=12345,RESOLUTION=320x180,CODECS="jpeg",URI="https://evil.example/Trickplay/320/tiles.m3u8"\n')
        out, reg = rewrite(master)
        self.assertNotIn("evil", out)
        self.assertNotIn("IMAGE", out)
        self.assertFalse(any("evil" in u for u, _ in reg.calls))
        media = ("#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXT-X-SERVER-CONTROL:CAN-BLOCK-RELOAD=YES,PART-HOLD-BACK=1.0\n"
                 "#EXT-X-PART-INF:PART-TARGET=0.5\n#EXT-X-PART:DURATION=0.5,URI=\"https://evil.example/p1.m4s\"\n"
                 "#EXTINF:4,\nseg.m4s\n#EXT-X-PRELOAD-HINT:TYPE=PART,URI=\"https://evil.example/p2.m4s\"\n"
                 "#EXT-X-RENDITION-REPORT:URI=\"https://evil.example/r.m3u8\",LAST-MSN=1\n")
        out, reg = rewrite(media)
        self.assertNotIn("evil", out)
        self.assertNotIn("PART", out)
        self.assertEqual(reg.calls, [("https://media.example/p/seg.m4s", "segment")])

    def test_refused(self):
        seg = "#EXTINF:4,\nseg.ts\n"
        head = "#EXTM3U\n#EXT-X-TARGETDURATION:4\n"
        cases = {
            "KEYFORMAT FairPlay": head + '#EXT-X-KEY:METHOD=AES-128,URI="k",KEYFORMAT="com.apple.streamingkeydelivery"\n' + seg,
            "KEYFORMATVERSIONS 2": head + '#EXT-X-KEY:METHOD=AES-128,URI="k",KEYFORMATVERSIONS="2"\n' + seg,
            "SAMPLE-AES": head + '#EXT-X-KEY:METHOD=SAMPLE-AES,URI="k"\n' + seg,
            "SAMPLE-AES-CTR": head + '#EXT-X-KEY:METHOD=SAMPLE-AES-CTR,URI="k"\n' + seg,
            "AES-128 without a URI": head + "#EXT-X-KEY:METHOD=AES-128\n" + seg,
            "NONE with a URI": head + '#EXT-X-KEY:METHOD=NONE,URI="k"\n' + seg,
            "unknown tag": head + "#EXT-X-FOO:1\n" + seg,
            "EXT-X-DEFINE": head + '#EXT-X-DEFINE:NAME="a",VALUE="b"\n' + seg,
            "I-FRAMES-ONLY": head + "#EXT-X-I-FRAMES-ONLY\n" + seg,
            "file URI": head + "#EXTINF:4,\nfile:///etc/passwd\n",
            "data URI": head + "#EXTINF:4,\ndata:video/mp2t;base64,AAAA\n",
            "file URI in a map": head + '#EXT-X-MAP:URI="file:///etc/passwd"\n' + seg,
            "URI with a space": head + "#EXTINF:4,\nseg 1.ts\n",
            "malformed attributes": head + '#EXT-X-KEY:METHOD=AES-128,URI="k"x\n' + seg,
            "trailing comma": head + '#EXT-X-KEY:METHOD=AES-128,URI="k",\n' + seg,
            "space in the attribute list": head + '#EXT-X-KEY:METHOD=AES-128, URI="k"\n' + seg,
            "duplicate attribute": head + '#EXT-X-KEY:METHOD=AES-128,URI="k",URI="j"\n' + seg,
            "unknown attribute": head + '#EXT-X-MAP:URI="init.mp4",X-OTHER-URI="https://evil.example/x"\n' + seg,
            "unquoted URI": head + "#EXT-X-MAP:URI=init.mp4\n" + seg,
            "no TARGETDURATION": "#EXTM3U\n" + seg,
            "URI without EXTINF": head + "seg.ts\n",
            "EXTINF without a URI": head + "#EXTINF:4,\n",
            "two EXTINFs": head + "#EXTINF:4,\n#EXTINF:4,\nseg.ts\n",
            "bad EXTINF": head + "#EXTINF:four,\nseg.ts\n",
            "two TARGETDURATIONs": head + "#EXT-X-TARGETDURATION:4\n" + seg,
            "ENDLIST with a value": head + seg + "#EXT-X-ENDLIST:1\n",
            "PLAYLIST-TYPE LIVE": head + "#EXT-X-PLAYLIST-TYPE:LIVE\n" + seg,
            "mixed master and media": head + seg + "#EXT-X-STREAM-INF:BANDWIDTH=1\nv.m3u8\n",
            "no #EXTM3U": "#EXT-X-TARGETDURATION:4\n" + seg,
            "nothing in it": "#EXTM3U\n",
            "control character": head + "#EXTINF:4,\x01\nseg.ts\n",
            "lone CR in a line": head + "#EXTINF:4,\rseg.ts\nseg.ts\n",
            "not UTF-8": (head + "#EXTINF:4,\xff\nseg.ts\n").encode("latin-1"),
        }
        for name, text in cases.items():
            reg = Recorder()
            with self.subTest(name):
                with self.assertRaises(Refused):
                    M.rewrite_playlist(text.encode() if isinstance(text, str) else text, "https://media.example/p/i.m3u8", 0, reg)
                self.assertEqual(reg.calls, [], "nothing is registered from a refused playlist")

    def test_master_refused(self):
        cases = {
            "CLOSED-CAPTIONS with a URI": MASTER.replace('INSTREAM-ID="CC1"', 'INSTREAM-ID="CC1",URI="cc.m3u8"'),
            "SUBTITLES group that isn't there": MASTER.replace('SUBTITLES="subs",CLOSED-CAPTIONS=NONE', 'SUBTITLES="other"'),
            "SUBTITLES rendition without a URI": MASTER.replace(',URI="subs/en.m3u8"', ""),
            "STREAM-INF without BANDWIDTH": "#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=1x1\nv.m3u8\n",
            "STREAM-INF without its URI": "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\n",
            "STREAM-INF then a tag": "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\n#EXT-X-STREAM-INF:BANDWIDTH=2\nv.m3u8\n",
            "unknown TYPE": MASTER.replace("TYPE=AUDIO", "TYPE=TEXT"),
            "only stripped tags": '#EXTM3U\n#EXT-X-SESSION-DATA:DATA-ID="a",VALUE="b"\n',
        }
        for name, text in cases.items():
            reg = Recorder()
            with self.subTest(name):
                with self.assertRaises(Refused):
                    M.rewrite_playlist(text.encode(), "https://media.example/p/i.m3u8", 0, reg)
                self.assertEqual(reg.calls, [])

    def test_master_inside_a_master(self):
        with self.assertRaises(Refused):
            rewrite(MASTER, depth=1)
        out, reg = rewrite(MEDIA, depth=1)            # a master's child: a media playlist, fine
        self.assertTrue(reg.calls)
        with self.assertRaises(Refused):
            rewrite(MEDIA, depth=2)

    def test_register_refusing_refuses_it_all(self):
        reg = Recorder(refuse=lambda url, kind: "keys.example" in url)
        with self.assertRaises(Refused):
            M.rewrite_playlist(MEDIA.encode(), "https://cdn.example/a/b/index.m3u8", 0, reg)

    def test_uri_cap(self):
        many = "#EXTM3U\n#EXT-X-TARGETDURATION:1\n" + "#EXTINF:1,\ns.ts\n" * 20001
        reg = Recorder()
        with self.assertRaises(Refused):
            M.rewrite_playlist(many.encode(), "https://media.example/i.m3u8", 0, reg)
        self.assertEqual(reg.calls, [])
        ok = "#EXTM3U\n#EXT-X-TARGETDURATION:1\n" + "#EXTINF:1,\ns.ts\n" * 20000
        out, reg = rewrite(ok)
        self.assertEqual(len(reg.calls), 20000)

    def test_byte_cap(self):
        text = "#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\ns.ts\n"
        big = text + "#" + "x" * (M.MAX_PLAYLIST - len(text)) + "\n"
        with self.assertRaises(Refused):
            M.rewrite_playlist(big.encode(), "https://media.example/i.m3u8", 0, Recorder())
        self.assertGreater(len(big.encode()), M.MAX_PLAYLIST)

    def test_final_url_must_be_http(self):
        with self.assertRaises(Refused):
            M.rewrite_playlist(MEDIA.encode(), "file:///tmp/i.m3u8", 0, Recorder())

    def test_start_tag(self):
        out, reg = rewrite("#EXTM3U\n#EXT-X-START:TIME-OFFSET=-12.5,PRECISE=YES\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\ns.ts\n")
        self.assertIn("#EXT-X-START:TIME-OFFSET=-12.5,PRECISE=YES", out)


# ---- real files, when FFmpeg is here ---------------------------------------------------

@unittest.skipUnless(os.access(FFMPEG, os.X_OK), "no /usr/bin/ffmpeg")
class RealFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="appmedia-")
        cls.dir = cls.tmp.name
        v = ["-f", "lavfi", "-i", "testsrc=size=64x48:rate=10"]
        a = ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100"]
        jobs = {
            "plain.mp4": v + a + ["-t", "2", "-c:v", "libx264", "-c:a", "aac"],
            "fast.mp4": v + a + ["-t", "2", "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart"],
            "audio.mp3": a + ["-t", "2", "-c:a", "libmp3lame"],
            "audio.aac": a + ["-t", "2", "-c:a", "aac", "-f", "adts"],
            "video.mkv": v + a + ["-t", "2", "-c:v", "libx264", "-c:a", "aac"],
            "video.webm": v + a + ["-t", "2", "-c:v", "libvpx", "-c:a", "libopus"],
            "video.ts": v + a + ["-t", "2", "-c:v", "libx264", "-c:a", "aac", "-f", "mpegts"],
            "audio.flac": a + ["-t", "2", "-c:a", "flac"],
            "audio.ogg": a + ["-t", "2", "-c:a", "libopus"],
        }
        cls.made = {}
        for name, args in jobs.items():
            out = os.path.join(cls.dir, name)
            r = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y"] + args + [out], capture_output=True)
            cls.made[name] = out if r.returncode == 0 else None
        hls = os.path.join(cls.dir, "hls")
        os.mkdir(hls)
        r = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y"] + v + a +
                           ["-t", "3", "-c:v", "libx264", "-g", "10", "-c:a", "aac", "-f", "hls", "-hls_time", "1",
                            "-hls_segment_type", "fmp4", "-hls_playlist_type", "vod", "-hls_fmp4_init_filename", "init.mp4",
                            "-hls_segment_filename", os.path.join(hls, "seg%d.m4s"), os.path.join(hls, "out.m3u8")],
                           capture_output=True)
        cls.hls = hls if r.returncode == 0 else None
        tsd = os.path.join(cls.dir, "hlsts")
        os.mkdir(tsd)
        r = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y"] + v + a +
                           ["-t", "3", "-c:v", "libx264", "-g", "10", "-c:a", "aac", "-f", "hls", "-hls_time", "1",
                            "-hls_playlist_type", "vod", "-hls_segment_filename", os.path.join(tsd, "seg%d.ts"),
                            os.path.join(tsd, "out.m3u8")], capture_output=True)
        cls.hlsts = tsd if r.returncode == 0 else None

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def probe(self, path):
        with open(path, "rb") as f:
            data = f.read(M.PROBE)
        return data, os.path.getsize(path) <= M.PROBE

    def test_direct_files(self):
        want = {"plain.mp4": "mp4", "fast.mp4": "mp4", "audio.mp3": "mp3", "audio.aac": "aac", "video.mkv": "matroska",
                "video.webm": "webm", "video.ts": "ts", "audio.flac": "flac", "audio.ogg": "ogg"}
        for name, fmt in want.items():
            with self.subTest(name):
                path = self.made.get(name)
                if not path:
                    self.skipTest("ffmpeg couldn't make " + name)
                data, complete = self.probe(path)
                self.assertEqual(M.sniff(data), "media")
                self.assertEqual(M.check_media("direct", data, complete), fmt)

    def test_box_layouts(self):
        # the two layouts the design names, as FFmpeg writes them
        def top(path):
            with open(path, "rb") as f:
                data = f.read()
            out, pos = [], 0
            while pos + 8 <= len(data):
                size, kind = struct.unpack(">I4s", data[pos:pos + 8])
                out.append(kind)
                pos += size
            return out
        if self.made.get("plain.mp4") and self.made.get("fast.mp4"):
            self.assertLess(top(self.made["plain.mp4"]).index(b"mdat"), top(self.made["plain.mp4"]).index(b"moov"))
            self.assertLess(top(self.made["fast.mp4"]).index(b"moov"), top(self.made["fast.mp4"]).index(b"mdat"))

    def test_hls_fmp4(self):
        if not self.hls:
            self.skipTest("ffmpeg couldn't make an fMP4 HLS stream")
        with open(os.path.join(self.hls, "out.m3u8"), "rb") as f:
            text = f.read()
        self.assertEqual(M.sniff(text), "playlist")
        reg = Recorder()
        M.rewrite_playlist(text, "http://127.0.0.1:8096/videos/x/out.m3u8", 0, reg)
        kinds = [k for _, k in reg.calls]
        self.assertEqual(kinds[0], "map")
        self.assertTrue(kinds[1:] and all(k == "segment" for k in kinds[1:]))
        data, complete = self.probe(os.path.join(self.hls, "init.mp4"))
        self.assertEqual(M.check_media("map", data, complete), "fmp4-init")
        for name in sorted(os.listdir(self.hls)):
            if name.endswith(".m4s"):
                with self.subTest(name):
                    data, complete = self.probe(os.path.join(self.hls, name))
                    self.assertEqual(M.check_media("segment", data, complete), "fmp4-segment")

    def test_hls_ts(self):
        if not self.hlsts:
            self.skipTest("ffmpeg couldn't make a TS HLS stream")
        with open(os.path.join(self.hlsts, "out.m3u8"), "rb") as f:
            reg = Recorder()
            M.rewrite_playlist(f.read(), "https://media.example/x/out.m3u8", 0, reg)
        self.assertTrue(reg.calls and all(k == "segment" for _, k in reg.calls))
        for name in sorted(os.listdir(self.hlsts)):
            if name.endswith(".ts"):
                with self.subTest(name):
                    data, complete = self.probe(os.path.join(self.hlsts, name))
                    self.assertEqual(M.check_media("segment", data, complete), "ts")


if __name__ == "__main__":
    unittest.main()
