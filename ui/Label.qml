import QtQuick

// Text drawn from an element's text style (Look.js): its color, font, size,
// weight, case, letter spacing and slant. sizeFactor scales the size where
// the guide shrinks an element (channel numbers with logos on, say).
Text {
  id: label

  property var s: ({})            // the element's style, resolved; its text is used
  property real unit: 16          // what a size of 1 is, in pixels
  property real sizeFactor: 1
  property string fallbackFont: ""

  readonly property var t: s && s.text ? s.text : ({})

  textFormat: Text.PlainText
  color: t.color || "white"
  font.family: t.font || fallbackFont
  font.pixelSize: Math.max(1, (t.size || 1) * unit * sizeFactor)
  font.weight: t.weight || Font.Normal
  font.italic: t.italic === true
  font.letterSpacing: (t.letterSpacing || 0) * unit
  font.capitalization: t.case === "upper" ? Font.AllUppercase : t.case === "lower" ? Font.AllLowercase
                     : t.case === "title" ? Font.Capitalize : Font.MixedCase
}
