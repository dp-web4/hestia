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

android {
    compileSdk = 36
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
            // Sideload signing: release builds are signed with the debug
            // keystore until a store-grade key lands (CI secret). Optimized
            // Rust profile keeps the APK small vs ~535 MB for a
            // debug-buildType build (dev-profile .so × 4 ABIs — run
            // 27447945048). Replace with a real signingConfig for stores.
            signingConfig = signingConfigs.getByName("debug")
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