import java.net.URL
import java.io.FileOutputStream
import java.util.zip.ZipInputStream

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    id("kotlin-kapt") // Required for ObjectBox to generate code
    id("io.objectbox")
}

// Download text embedder model if missing (BERT 768-dim)
val modelFile = file("src/main/assets/universal_sentence_encoder.tflite")
tasks.register("downloadTextEmbedder") {
    outputs.file(modelFile)
    onlyIf { !modelFile.exists() }
    doLast {
        modelFile.parentFile.mkdirs()
        URL("https://storage.googleapis.com/mediapipe-models/text_embedder/bert_embedder/float32/1/bert_embedder.tflite")
            .openStream().use { input ->
                FileOutputStream(modelFile).use { output ->
                    input.copyTo(output)
                }
            }
    }
}
tasks.named("preBuild") { dependsOn("downloadTextEmbedder", "downloadVoskModel") }

val voskModelDir = file("src/main/assets/vosk-model-small-en-us-0.15")
tasks.register("downloadVoskModel") {
    outputs.dir(voskModelDir)
    onlyIf { !voskModelDir.exists() || voskModelDir.list()?.isEmpty() == true }
    doLast {
        voskModelDir.parentFile.mkdirs()
        val zipUrl = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
        URL(zipUrl).openStream().use { input ->
            ZipInputStream(input).use { zip ->
                var entry = zip.nextEntry
                while (entry != null) {
                    val outFile = file("src/main/assets/${entry.name}")
                    if (entry.isDirectory) {
                        outFile.mkdirs()
                    } else {
                        outFile.parentFile.mkdirs()
                        FileOutputStream(outFile).use { zip.copyTo(it) }
                    }
                    zip.closeEntry()
                    entry = zip.nextEntry
                }
            }
        }
    }
}

android {
    namespace = "com.example.gemmaapp"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.example.gemmaapp"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlinOptions {
        jvmTarget = "11"
    }
    packaging {
        jniLibs { useLegacyPackaging = true }
    }
}

dependencies {

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.material)
    implementation(libs.androidx.activity)
    implementation(libs.androidx.constraintlayout)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    implementation("com.google.mediapipe:tasks-genai:0.10.27")
    implementation("com.google.mediapipe:tasks-text:0.10.29")
    kapt("io.objectbox:objectbox-processor:4.0.3")

    implementation("io.objectbox:objectbox-android:4.0.3")
    implementation("com.alphacephei:vosk-android:0.3.75")
    implementation("net.java.dev.jna:jna:5.18.0@aar")
}