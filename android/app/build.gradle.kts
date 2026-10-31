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
        versionCode = 19
        versionName = "0.18"
        // Phones (arm64) and the emulator (x86_64): Pillow is built for these.
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

// The Studio's weather module, as it is in the integration: copied at build time.
val meteoPython = layout.buildDirectory.dir("generated/meteo")
val copyMeteo by tasks.registering(Copy::class) {
    from("../../custom_components/idotmatrix") { include("meteo.py", "weather.py", "emoji.py", "pages.py", "texts_fr.json") }
    into(meteoPython.map { it.dir("idm") })
    doLast { meteoPython.get().file("idm/__init__.py").asFile.writeText("") }
}
tasks.configureEach {
    if (name != copyMeteo.name && name.contains("Python")) dependsOn(copyMeteo)
}

chaquopy {
    defaultConfig {
        version = "3.13"
        // Chaquopy compiles with a Python of the same version on the build machine.
        System.getenv("CHAQUOPY_BUILD_PYTHON")?.let { buildPython(it) }
        pip {
            install("pillow")
            install("voluptuous")
        }
    }
    sourceSets {
        getByName("main") { srcDir(meteoPython) }
    }
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
}
