# Pratham AI Mobile (Android APK & React Native)

Official mobile application for **Pratham AI**, created by **Pratham Sinha and team** under the supervision of **Akriti & Aditi Aishwaryam**.

---

## Quick Start & APK Building

### Method 1: Local Android APK Build (Ready Instantly)
The native Android project is fully pre-configured in `mobile/android/` with Java 17 and Android SDK 35 support.

1. Navigate to the `mobile/android` directory:
   ```bash
   cd /workspace/bold-curie/mobile/android
   ```
2. Build the APK using the Gradle wrapper:
   ```bash
   ./gradlew assembleDebug
   ```
   *(Or from `mobile/`, run: `npm run build:local`)*

3. Your compiled APK will be at:
   ```
   mobile/android/app/build/outputs/apk/debug/app-debug.apk
   ```

---

### Method 2: EAS Cloud APK Build (Recommended for Standalone Release)
We have updated `package.json` with `npx --yes eas-cli` so you do **not** need to install `eas` globally.

1. Navigate to `mobile/`:
   ```bash
   cd /workspace/bold-curie/mobile
   ```
2. Run the build script:
   ```bash
   npm run build:apk
   ```
3. Follow the Expo prompt to log in and EAS will build an installable release `.apk` in the cloud with a direct download link.

---

## App Features
- **Collapsible Thought Process**: Detailed thinking steps (*Analyzing*, *Planning*, *Executing*, *Presenting*).
- **Deliverables Engine**: Dedicated interactive cards to download generated HTML games (e.g. 3D Stumble Guys, Chess), Python scripts, and ZIP packages.
- **Dual Antigravity Accounts**: Real-time status badge showing Primary (`manojkumarsinha1972@gmail.com`) and Standby (`pratham31sinha@gmail.com`) with sub-second `<0.1s` failover.
- **Multi-Modal Attachments**: Integrated document, camera, and gallery pickers.
- **Offline + Online Resilience**: Bundled standalone assets with dynamic backend connectivity.
