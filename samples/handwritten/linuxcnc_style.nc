; LinuxCNC-style program: semicolon comments, G64 blending, O-word subroutine
; two 30 x 15 window pockets cut by one incremental subroutine
G21 G90 G64 P0.02
T1 M6 ; 6mm end mill
S8000 M3
o100 sub
  G91
  G1 Z-7 F150
  G1 X24 F600
  G1 Y3
  G1 X-24
  G1 Y3
  G1 X24
  G1 Y3
  G1 X-24
  G1 Y-9
  G90
  G0 Z5
o100 endsub
G0 X3 Y3 Z5
G0 Z1
o100 call
G0 X43 Y3
G0 Z1
o100 call
M5
M2
