# Record the 60-second demo as a GIF with charmbracelet/vhs:
#   brew install vhs
#   vhs scripts/demo.tape            # English narration -> docs/assets/demo.gif
# For the Chinese version, change the Type line to "scripts/demo.sh" and the
# Output to docs/assets/demo-zh.gif.
Output docs/assets/demo.gif

Set FontSize 18
Set Width 1200
Set Height 720
Set Padding 24
Set TypingSpeed 40ms

Type "scripts/demo.sh --en"
Sleep 400ms
Enter
Sleep 9s
