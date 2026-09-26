# Pratham AI Mobile (React Native / Android APK)

Official React Native mobile application for **Pratham AI**, created by **Pratham Sinha and team** under the supervision of **Akriti & Aditi Aishwaryam**.

## Features

- **Full Mobile Optimization**: Native look and feel, responsive layout, safe-area inset management for notches and edge-to-edge displays.
- **Thinking / Planning Accordion**: Interactive, collapsible thought process indicator with dynamic step-by-step progress cards.
- **Syntax-Highlighted Code Blocks**: Built-in copy-to-clipboard, language badges, and direct file export.
- **Interactive Deliverables**: Dedicated download and export cards for generated HTML games, Python scripts, archives, and documents.
- **Multi-Modal Attachment Suite**:
  - 📷 Camera capture
  - 🖼️ Photo gallery picker
  - 📄 Document and code file picker
- **Dual Antigravity Account Badge**: Real-time status display showing Primary (`manojkumarsinha1972@gmail.com`) and Failover Standby (`pratham31sinha@gmail.com`) with sub-second `<0.1s` failover indicator.
- **Web Search Toggle**: Toggle live web search on or off directly from the composer.
- **Configurable Backend Host**: Seamlessly connect to your production Vercel deployment or local Flask instance.

---

## Building the Standalone Android APK

### Option 1: Cloud Build with EAS (Recommended & Fastest)

1. Install EAS CLI:
   ```bash
   npm install -g eas-cli
   ```
2. Log in to your Expo account:
   ```bash
   eas login
   ```
3. Run the APK build:
   ```bash
   npm run build:apk
   ```
   *EAS will compile a standalone `.apk` installable on any Android phone and provide a direct download link.*

---

### Option 2: Local Gradle Build (Local Machine)

1. Prebuild the native Android project:
   ```bash
   npx expo prebuild --platform android
   ```
2. Navigate to `android/` and assemble the release APK:
   ```bash
   cd android
   ./gradlew assembleRelease
   ```
3. Your output APK will be ready at:
   `android/app/build/outputs/apk/release/app-release.apk`
