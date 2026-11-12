# Chaquopy loads Python modules dynamically; preserve its runtime bridge.
-keep class com.chaquo.python.** { *; }
-keep class com.ABDO10DZ.OpenGDS.** { *; }
-dontwarn com.chaquo.python.**

# APK signing and verification are invoked directly by the editor export pipeline.
-keep class com.android.apksig.** { *; }
-dontwarn com.android.apksig.**
