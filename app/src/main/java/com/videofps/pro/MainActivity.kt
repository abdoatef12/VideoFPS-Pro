package com.videofps.pro

import android.annotation.SuppressLint
import android.app.Activity
import android.os.Bundle
import android.webkit.*

class MainActivity : Activity() {

    // السيرفر بيشتغل في Termux على نفس التليفون
    private val SERVER_URL = "http://127.0.0.1:5000"
    private var webView: WebView? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val web = WebView(this)
        webView = web
        setContentView(web)

        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = true
            mediaPlaybackRequiresUserGesture = false
        }

        web.webViewClient = object : WebViewClient() {
            override fun onReceivedError(
                view: WebView, request: WebResourceRequest, error: WebResourceError
            ) {
                if (request.isForMainFrame) {
                    view.loadData(
                        "<html dir='rtl'><body style='background:#0b0d14;color:#eee;" +
                        "font-family:sans-serif;text-align:center;padding-top:40vh'>" +
                        "<h2>السيرفر مش شغال</h2>" +
                        "<p>افتح Termux واكتب: python VideoFPS_Pro.py</p>" +
                        "<p>وبعدين اضغط الزرار:</p>" +
                        "<button onclick='location.href=\"$SERVER_URL\"' " +
                        "style='padding:12px 24px;font-size:16px'>إعادة المحاولة</button>" +
                        "</body></html>",
                        "text/html; charset=utf-8", "utf-8"
                    )
                }
            }
        }

        // ملفات التحميل (MP4) تتفتح بالمتصفح/مدير التحميل
        web.setDownloadListener { url, _, _, _, _ ->
            val intent = android.content.Intent(
                android.content.Intent.ACTION_VIEW,
                android.net.Uri.parse(url)
            )
            startActivity(intent)
        }

        web.loadUrl(SERVER_URL)
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        val web = webView
        if (web != null && web.canGoBack()) web.goBack() else super.onBackPressed()
    }
}
