import QtQuick
import QtTest
import "../../ui"
import "../../Look.js" as Look
import "../../AppLooks.js" as Looks

// Where an app is from, as a small icon (ui/OriginBadge.qml):
// none for Uber TV's own, a page for a signed app
// file or an unsigned Developer-mode file; always solid, whatever the theme says (a see-through
// color is made opaque), never smaller than its floor, its icon reading on
// it (4.5:1), and the same pixels over black, white or a picture made to
// match it, in each built-in theme's colors (and an Omarchy one's).
Item {
  id: root
  width: 400
  height: 300

  // the built-in themes' box colors (Retro, OLED, Split-Flap; Terminal's
  // come from the Omarchy theme: a typical dark one here)
  readonly property var palettes: [
    { name: "retro", boxBg: "#071447", boxBorder: "#ffd23f" },
    { name: "oled", boxBg: "#141416", boxBorder: "#2a2a2e" },
    { name: "split-flap", boxBg: "#121212", boxBorder: "#ffc233" },
    { name: "terminal", boxBg: "#2c2e3e", boxBorder: "#7aa2f7" },
    { name: "light", boxBg: "#f4f4f4", boxBorder: "#888888" },
    { name: "middle", boxBg: "#777777", boxBorder: "#333333" }
  ]

  QtObject {
    id: guide
    property real u: 16
    property var colors: ({ boxBg: "#071447", boxBorder: "#ffd23f" })
    property var look: ({ appOrigin: { color: "#071447", edge: "#ffd23f", size: 1.7 } })
  }

  Rectangle { id: behind; anchors.fill: parent; color: "black" }
  Image { id: picture; anchors.fill: parent; visible: false }

  OriginBadge { id: badge; guide: guide; x: 40; y: 40; from: "appFile" }

  TestCase {
    name: "OriginBadge"
    when: windowShown

    function pixel(img, x, y) {
      var p = img.pixel(Math.round(badge.x + x), Math.round(badge.y + y))
      return String(p)
    }

    function test_which_badge() {
      badge.from = "appFile"
      verify(badge.visible)
      badge.from = "file"
      verify(badge.visible)
      for (var f of ["bundled", "catalog", ""]) {
        badge.from = f
        verify(!badge.visible, "none for Uber TV's own: " + f)
      }
      badge.from = "appFile"
    }

    function test_solid_and_readable_in_each_theme() {
      for (var p of root.palettes) {
        guide.look = { appOrigin: { color: p.boxBg, edge: p.boxBorder, size: 1.7 } }
        compare(badge.color.a, 1, p.name + ": solid")
        verify(Looks.contrast(String(badge.ink), String(badge.color)) >= 4.5, p.name + ": its icon reads " + Looks.contrast(String(badge.ink), String(badge.color)))
      }
    }

    function test_a_theme_cant_make_it_see_through_or_tiny() {
      guide.look = { appOrigin: { color: "#00ff0000", edge: "#00000000", size: 0.1 } }
      compare(badge.color.a, 1, "a see-through fill made solid")
      compare(badge.border.color.a, 1)
      verify(badge.width >= Math.round(guide.u * 1.4), "never under its floor")
      guide.look = ({})
      compare(String(badge.color), String(Qt.color(guide.colors.boxBg)), "no part: the box's colors")
      verify(badge.width >= Math.round(guide.u * 1.4))
    }

    // the same pixels whatever's behind it: black, white, and a picture the
    // same color as its icon and as its fill
    function test_nothing_behind_shows_through() {
      for (var p of root.palettes) {
        guide.look = { appOrigin: { color: p.boxBg, edge: p.boxBorder, size: 1.7 } }
        for (var from of ["appFile", "file"]) {
          badge.from = from
          var seen = null
          for (var bg of ["#000000", "#ffffff", String(badge.ink), String(badge.color)]) {
            behind.color = bg
            wait(30)
            var img = grabImage(root)
            var w = badge.width
            var points = [[w * 0.12, w * 0.5], [w * 0.5, w * 0.12], [w * 0.5, w * 0.5], [w * 0.3, w * 0.7], [w * 0.7, w * 0.3]]
            var got = points.map(function(q) { return pixel(img, q[0], q[1]) }).join(" ")
            if (seen === null) seen = got
            compare(got, seen, p.name + "/" + from + ": the same over " + bg)
          }
        }
      }
      behind.color = "black"
      badge.from = "appFile"
    }
  }
}
