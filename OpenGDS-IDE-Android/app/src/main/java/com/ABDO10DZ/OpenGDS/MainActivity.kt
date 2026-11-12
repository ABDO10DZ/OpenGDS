package com.ABDO10DZ.OpenGDS

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.LayoutDirection
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import com.ABDO10DZ.OpenGDS.data.OpenGDSViewModel
import com.ABDO10DZ.OpenGDS.ui.OpenGDSRoot
import com.ABDO10DZ.OpenGDS.ui.theme.OpenGDSTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val model: OpenGDSViewModel = viewModel()
            val appState by model.state.collectAsState()
            OpenGDSTheme(appState.theme) {
                CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
                    OpenGDSRoot(model)
                }
            }
        }
    }
}
