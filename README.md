# app_warehouse

Farmoish POS Android APK'lari. Bu yerda chop etilgan har bir release ilovaning
ichki yangilanishiga aylanadi: "Publish In-App Update" workflow'i APK'ni
tekshiradi va versiyani Firebase Remote Config'ga yozadi — ilovalarda
"Доступно обновление" oynasi chiqadi.

## Yangi versiya chiqarish

1. `farmoish-pos-app` → `pubspec.yaml` → `version:` ni oshiring
   (masalan `1.0.11+11` → `1.0.12+12`). `+` dan keyingi raqam har safar
   oldingisidan katta bo'lsin.
2. `android/key.properties` bor kompyuterda build qiling:
   ```bash
   flutter build apk --release
   ```
   APK: `build/app/outputs/flutter-apk/app-release.apk`
3. APK'ni release qilib yuklang:
   - https://github.com/farmoish/app_warehouse/releases → **Draft a new release**
   - **Choose a tag** → `v1.0.12` deb yozing → **Create new tag**
   - Title: `Farmoish POS 1.0.12`
   - APK'ni **Attach binaries** maydoniga sudrab tashlang (fayl nomi ixtiyoriy)
   - **Publish release**

   Yoki terminalda, `farmoish-pos-app` papkasidan:
   ```bash
   gh release create v1.0.12 build/app/outputs/flutter-apk/app-release.apk --repo farmoish/app_warehouse --title "Farmoish POS 1.0.12"
   ```
4. **Actions** → "Publish In-App Update" yashil bo'lsa, versiya Firebase'ga yozilgan.

Majburiy/ixtiyoriy yangilanish: Firebase console → Remote Config →
`android_force_update` (`true` / `false`) → **Publish changes**.

## Qurilmaga birinchi o'rnatish

Eski ilovani o'chiring → brauzerda
https://github.com/farmoish/app_warehouse/releases/latest → APK'ni yuklab oling
→ o'rnating. Keyingi versiyalar ilovaning o'zida taklif qilinadi.

## Bir martalik sozlash

Settings → Secrets and variables → Actions → **New repository secret**:
`FIREBASE_SERVICE_ACCOUNT_JSON` — "Firebase Remote Config Admin" rolidagi
service account'ning JSON kaliti.
