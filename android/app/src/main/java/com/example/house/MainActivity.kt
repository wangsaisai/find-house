package com.example.house

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.example.house.network.ApiService
import com.example.house.network.RentalLocationRequest
import com.example.house.ui.theme.HouseTheme
import io.noties.markwon.Markwon
import io.noties.markwon.ext.tables.TablePlugin
import io.noties.markwon.html.HtmlPlugin
import io.noties.markwon.image.coil.CoilImagesPlugin
import io.noties.markwon.linkify.LinkifyPlugin
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            HouseTheme {
                // A surface container using the 'background' color from the theme
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    MainScreen()
                }
            }
        }
    }
}

@Composable
fun MainScreen() {
    var workAddress1 by remember { mutableStateOf("浦东外高桥-药明康德") }
    var workAddress2 by remember { mutableStateOf("浦东张江-联想") }
    var budgetRange by remember { mutableStateOf("") }
    var preferences by remember { mutableStateOf("") }
    var isLoading by remember { mutableStateOf(false) }
    var analysisResult by remember { mutableStateOf<String?>(null) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(text = "租房位置智能分析", style = MaterialTheme.typography.headlineMedium)
        Spacer(modifier = Modifier.height(8.dp))
        Text(text = "输入两个日常通勤地址，我们将为您推荐最合适的租房区域。")
        Spacer(modifier = Modifier.height(16.dp))

        OutlinedTextField(
            value = workAddress1,
            onValueChange = { workAddress1 = it },
            label = { Text("工作/学习地点 A") },
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(modifier = Modifier.height(8.dp))

        OutlinedTextField(
            value = workAddress2,
            onValueChange = { workAddress2 = it },
            label = { Text("工作/学习地点 B") },
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(modifier = Modifier.height(8.dp))

        OutlinedTextField(
            value = budgetRange,
            onValueChange = { budgetRange = it },
            label = { Text("预算范围 (可选)") },
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(modifier = Modifier.height(8.dp))

        OutlinedTextField(
            value = preferences,
            onValueChange = { preferences = it },
            label = { Text("其他偏好 (可选)") },
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(modifier = Modifier.height(16.dp))

        Button(
            onClick = {
                isLoading = true
                analysisResult = null
                val request = RentalLocationRequest(
                    work_address1 = workAddress1,
                    work_address2 = workAddress2,
                    budget_range = budgetRange.ifEmpty { "不限" },
                    preferences = preferences
                )
                CoroutineScope(Dispatchers.IO).launch {
                    try {
                        val response = ApiService.create().findRentalLocation(request)
                        withContext(Dispatchers.Main) {
                            analysisResult = response.rental_location_analysis
                            isLoading = false
                        }
                    } catch (e: Exception) {
                        withContext(Dispatchers.Main) {
                            analysisResult = "Error: ${e.message}"
                            isLoading = false
                        }
                    }
                }
            },
            enabled = !isLoading,
            modifier = Modifier.fillMaxWidth()
        ) {
            Text(text = if (isLoading) "分析中..." else "开始分析")
        }

        if (isLoading) {
            Spacer(modifier = Modifier.height(16.dp))
            CircularProgressIndicator()
            Spacer(modifier = Modifier.height(8.dp))
            Text(text = "正在玩命分析中，请稍候... (通常需要1-2分钟)")
        }

        analysisResult?.let {
            Spacer(modifier = Modifier.height(16.dp))
            Text(text = "分析报告", style = MaterialTheme.typography.headlineSmall)
            Spacer(modifier = Modifier.height(8.dp))
            MarkdownText(markdown = it)
        }
    }
}

@Composable
fun MarkdownText(markdown: String) {
    val context = LocalContext.current
    val markwon = remember {
        Markwon.builder(context)
            .usePlugin(HtmlPlugin.create())
            .usePlugin(CoilImagesPlugin.create(context))
            .usePlugin(TablePlugin.create(context))
            .usePlugin(LinkifyPlugin.create())
            .build()
    }
    AndroidView(
        factory = { ctx ->
            android.widget.TextView(ctx).apply {
                markwon.setMarkdown(this, markdown)
            }
        },
        update = {
            markwon.setMarkdown(it, markdown)
        }
    )
}

@Preview(showBackground = true)
@Composable
fun DefaultPreview() {
    HouseTheme {
        MainScreen()
    }
}
