# Inter — vendored for rasterisation

The design system specifies Inter, but the SVG only *names* it: nothing is
embedded. Until these files existed, no card had ever rendered in Inter — every
image fell back to a generic grotesque, on this machine and anywhere else.

Only the five weights `design_system.FontWeight` actually uses are vendored
(Regular 400, SemiBold 600, Bold 700, ExtraBold 800, Black 900). Licence: SIL
Open Font License, see LICENSE.txt — free to bundle and redistribute.

**Rasterise with resvg, not cairosvg.** Measured: cairosvg could not find these
fonts even when the family was named explicitly, and rendered every weight
identically — which collapses the whole typographic hierarchy (900 figures, 800
headlines, 600 labels) into one. resvg loads them from this directory
explicitly, so the result does not depend on the host's fontconfig state:

    resvg --use-fonts-dir <this dir> --skip-system-fonts --font-family Inter \
          --width 1080 --height 1350 card.svg card.png

~0.33s per card.
