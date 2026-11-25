; Agent Control Room installer hooks.
; Tauri's installer puts the app in the Start menu; this makes sure there is a desktop icon too,
; and takes it away again when the app is uninstalled.
!macro NSIS_HOOK_POSTINSTALL
  CreateShortcut "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  Delete "$DESKTOP\${PRODUCTNAME}.lnk"
!macroend
