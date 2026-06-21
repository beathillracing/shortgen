import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.google.gms.google-services")
}

val localProperties = Properties().apply {
    rootProject.file("local.properties").inputStream().use(::load)
}

android {
    namespace = "fi.beathillracing.shortgen"
    compileSdk = 35

    flavorDimensions += listOf("edition", "distribution")

    defaultConfig {
        applicationId = "fi.beathillracing.shortgen"
        minSdk = 26
        targetSdk = 35
        versionCode = 21
        versionName = "0.11.1"
    }

    productFlavors {
        create("full") {
            dimension = "edition"
            buildConfigField("boolean", "CREATOR_MODE", "false")
            resValue("string", "app_name", "Beathill Studio")
        }
        create("creator") {
            dimension = "edition"
            applicationIdSuffix = ".creator"
            versionNameSuffix = "-creator"
            buildConfigField("boolean", "CREATOR_MODE", "true")
            resValue("string", "app_name", "Beathill Studio Creator")
        }
        create("direct") {
            dimension = "distribution"
        }
        create("play") {
            dimension = "distribution"
            applicationId = "beathill.studio"
            buildConfigField(
                "String",
                "GOOGLE_WEB_CLIENT_ID",
                "\"724672739628-hlkhoh5h4u74hp6r3cvaml4j8inmm90f.apps.googleusercontent.com\"",
            )
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    signingConfigs {
        create("release") {
            storeFile = file(localProperties.getProperty("shortgen.storeFile"))
            storePassword = localProperties.getProperty("shortgen.storePassword")
            keyAlias = localProperties.getProperty("shortgen.keyAlias")
            keyPassword = localProperties.getProperty("shortgen.keyPassword")
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = false
        }
    }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.04.01"))
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.0")
    implementation("androidx.work:work-runtime-ktx:2.10.1")
    implementation("androidx.media3:media3-exoplayer:1.6.1")
    implementation("androidx.media3:media3-ui:1.6.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    "playImplementation"("com.android.billingclient:billing:9.1.0")
    "playImplementation"("androidx.credentials:credentials:1.6.0")
    "playImplementation"("androidx.credentials:credentials-play-services-auth:1.6.0")
    "playImplementation"("com.google.android.libraries.identity.googleid:googleid:1.2.0")
    "playImplementation"("com.google.android.play:app-update:2.1.0")
    "playImplementation"(platform("com.google.firebase:firebase-bom:33.7.0"))
    "playImplementation"("com.google.firebase:firebase-messaging")

    debugImplementation("androidx.compose.ui:ui-tooling")
}
