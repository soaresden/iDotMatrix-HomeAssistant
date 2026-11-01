plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "org.idotmatrix.pixelmeteo"
    compileSdk = 35

    defaultConfig {
        applicationId = "org.idotmatrix.pixelmeteo"
        minSdk = 24
        targetSdk = 35
        versionCode = 20
        versionName = "1.0"
        // Phones (arm64) and the emulator (x86_64): Pillow is built for these.
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

// The Studio as on the PC (tools/build_pixel_studio_exe.ps1), copied at build time:
// idmcore, the integration's Studio modules (with the PC's coordinator), and desktop,
// the PC app's server with its stand-in for Home Assistant.
val studioPython = layout.buildDirectory.dir("generated/studio")
val copyStudio by tasks.registering(Copy::class) {
    val integration = "../../custom_components/idotmatrix"
    into(studioPython)
    from(integration) {
        include("studio.py", "journal.py", "routines.py", "schedule.py", "media.py", "weather.py", "meteo.py",
            "emoji.py", "pages.py", "preview.py", "const.py", "texts_fr.json", "client/**", "www/idotmatrix-studio.js")
        exclude("**/__pycache__/**")
        into("idmcore")
    }
    from("../../desktop/overrides/coordinator.py") { into("idmcore") }
    from("../../desktop") {
        include("pixel_studio.py", "index.html", "homeassistant/**")
        exclude("**/__pycache__/**")
        into("desktop")
    }
    doLast {
        studioPython.get().file("idmcore/__init__.py").asFile.writeText("")
        studioPython.get().file("desktop/__init__.py").asFile.writeText("")
    }
}
tasks.configureEach {
    if (name != copyStudio.name && name.contains("Python")) dependsOn(copyStudio)
}

chaquopy {
    defaultConfig {
        version = "3.13"
        // Chaquopy compiles with a Python of the same version on the build machine.
        System.getenv("CHAQUOPY_BUILD_PYTHON")?.let { buildPython(it) }
        pip {
            install("pillow")
            install("voluptuous")
            install("aiohttp")
            install("cryptography")
        }
        // Read as files by the server (its page, the Studio's panel, the texts).
        extractPackages("idmcore", "desktop")
    }
    sourceSets {
        getByName("main") { srcDir(studioPython) }
    }
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
}
