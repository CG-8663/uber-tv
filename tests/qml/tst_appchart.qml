import QtQuick
import QtTest
import "../../ui"
import "../../Look.js" as Look

// ui/AppChart.qml (api 4): a chart's line from its points, every coordinate
// a finite number, even for the largest finite numbers an app may send.
// Run: /usr/lib/qt6/bin/qmltestrunner -input tests/qml
Item {
  id: root
  width: 400
  height: 200

  QtObject {
    id: guide
    property real u: 10
    readonly property var colors: ({ text: "#ffffff", textDim: "#aaaaaa", accent: "#ffd23f", bgBottom: "#000000" })
    readonly property var fonts: ({ body: "Sans", display: "Sans", mono: "Monospace" })
    readonly property var look: Look.resolve({}, {}, guide.colors, guide.fonts, {})
    readonly property color marquee: colors.accent
    readonly property color ink: colors.text
    readonly property color dimInk: colors.textDim
  }

  AppChart { id: chart; guide: guide; width: 300; height: 100; labels: false }

  TestCase {
    name: "AppChart"
    when: windowShown

    function finite(c) { return c.every(function(p) { return isFinite(p.x) && isFinite(p.y) }) }

    function test_an_ordinary_line() {
      chart.data = { points: [0, 5, 10], low: "", high: "" }
      wait(0)
      var c = chart.coords
      compare(c.length, 3)
      verify(finite(c))
      verify(c[0].y > c[1].y && c[1].y > c[2].y, "higher points higher up")
      verify(Math.abs(c[1].y - (c[0].y + c[2].y) / 2) < 0.01, "the middle value halfway")
    }

    function test_the_largest_finite_numbers() {
      chart.data = { points: [-1e308, 0, 1e308], low: "", high: "" }
      wait(0)
      var c = chart.coords
      verify(finite(c), "no NaN or Infinity in the path: " + JSON.stringify(c))
      verify(Math.abs(c[1].y - (c[0].y + c[2].y) / 2) < 0.01, "0 halfway between them")
      verify(c[2].y < c[0].y)
    }

    function test_a_flat_line() {
      chart.data = { points: [3, 3, 3, 3], low: "", high: "" }
      wait(0)
      var c = chart.coords
      verify(finite(c))
      verify(c.every(function(p) { return Math.abs(p.y - chart.height / 2) < 0.01 }), "across its middle")
    }
  }
}
