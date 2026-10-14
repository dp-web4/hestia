import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("rust")
}

val tauriProperties = Properties().apply {
    val propFile = file("tauri.properties")
    if (propFile.exists()) {
        propFile.inputStream().use { load(it) }
    }
}

// THE RELEASE KEY (dp, 2026-10-14, web4#904 signing option b). CI writes keystore.properties
// (storeFile, password, keyAlias, keyPassword) only when the release keystore is configured for
// the repo; it is gitignored and never committed. Without it the release build falls back to the
// debug keystore, so dry runs and forks still build. An APK signed by one key cannot be upgraded
// in place by an APK signed by the other: once the release key ships, it is the key for good.
val keystoreProperties = Properties().apply {
    val propFile = rootProject.file("keystore.properties")
    if (propFile.exists()) {
        propFile.inputStream().use { load(it) }
    }
}
val hasReleaseKey = keystoreProperties.getProperty("storeFile") != null

android {
    compileSdk = 36
    signingConfigs {
        if (hasReleaseKey) {
            create("release") {
                storeFile = rootProject.file(keystoreProperties.getProperty("storeFile"))
                storePassword = keystoreProperties.getProperty("password")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
            }
        }
    }
    namespace = "com.web4.hestia"
    defaultConfig {
        // Cleartext ON: the app talks to hestia daemons over http:// —
        // typically across a Tailscale tailnet, where transport is already
        // WireGuard-encrypted. Without this, release builds silently block
        // every daemon request. Revisit when the daemon serves TLS.
        manifestPlaceholders["usesCleartextTraffic"] = "true"
        applicationId = "com.web4.hestia"
        minSdk = 24
        targetSdk = 36
        versionCode = tauriProperties.getProperty("tauri.android.versionCode", "1").toInt()
        versionName = tauriProperties.getProperty("tauri.android.versionName", "1.0")
    }
    buildTypes {
        getByName("debug") {
            manifestPlaceholders["usesCleartextTraffic"] = "true"
            isDebuggable = true
            isJniDebuggable = true
            isMinifyEnabled = false
            packaging {                jniLibs.keepDebugSymbols.add("*/arm64-v8a/*.so")
                jniLibs.keepDebugSymbols.add("*/armeabi-v7a/*.so")
                jniLibs.keepDebugSymbols.add("*/x86/*.so")
                jniLibs.keepDebugSymbols.add("*/x86_64/*.so")
            }
        }
        getByName("release") {
            // Minify OFF: R8 with only the empty default proguard-rules.pro
            // risks stripping Tauri's reflection-accessed Kotlin plugin
            // classes. The APK bulk is the Rust .so files, which R8 never
            // touches — so minify buys little here and removes a whole
            // failure class. Revisit with proper tauri keep rules if size
            // matters later.
            isMinifyEnabled = false
            // Signed with the release key when keystore.properties exists (see the top of this
            // file), otherwise with the debug keystore. Optimized Rust profile keeps the APK small
            // vs ~535 MB for a debug-buildType build (dev-profile .so × 4 ABIs — run 27447945048).
            signingConfig = signingConfigs.getByName(if (hasReleaseKey) "release" else "debug")
            proguardFiles(
                *fileTree(".") { include("**/*.pro") }
                    .plus(getDefaultProguardFile("proguard-android-optimize.txt"))
                    .toList().toTypedArray()
            )
        }
    }
    kotlinOptions {
        jvmTarget = "1.8"
    }
    buildFeatures {
        buildConfig = true
    }
}

rust {
    rootDirRel = "../../../"
}

dependencies {
    implementation("androidx.webkit:webkit:1.14.0")
    implementation("androidx.appcompat:appcompat:1.7.1")
    implementation("androidx.activity:activity-ktx:1.10.1")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.lifecycle:lifecycle-process:2.10.0")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.1.4")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.0")
}

apply(from = "tauri.build.gradle.kts")