
### Added
- **Font Hinting Guard 1.0.0: protection against malicious fonts in resource packs.** A security bug in FreeType, the library Minecraft uses to draw TrueType fonts, lets a specially made font in a resource pack run code on your computer. Mojang fixed it for Minecraft 26.x but not for 1.21.1. This small mod of ours turns off font *hinting*, the part of FreeType where the bug lives, so a malicious font can't reach it. Minecraft's own text looks exactly the same; fonts from some resource packs may look slightly softer. Source and details: https://github.com/slashdaemon/fonthintguard
- It ships inside the pack itself rather than through CurseForge or Modrinth, so it's in every install the moment you update.

**Mods:** 184
