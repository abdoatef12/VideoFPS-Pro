package com.videofps.pro

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.webkit.*

class MainActivity : Activity() {

    private val serverUrl = "http://127.0.0.1:5000/"
    private val retryMs = 2000L
    private lateinit var web: WebView
    private val handler = Handler(Looper.getMainLooper())

    // لو السيرفر مش شغال، بنعيد المحاولة كل ثانيتين
    private val retry = Runnable { web.loadUrl(serverUrl) }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        web = WebView(this).apply {
            setBackgroundColor(Color.parseColor("#0b0d14"))
        }
        setContentView(web)

        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = false
        }

        web.webViewClient = object : WebViewClient() {
            override fun onReceivedError(
                view: WebView, request: WebResourceRequest, error: WebResourceError
            ) {
                if (request.isForMainFrame) showWaiting()
            }
        }

        // تحميل الملفات يتفتح بالتطبيق/مدير التحميل
        web.setDownloadListener { url, _, _, _, _ ->
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        }

        web.loadUrl(serverUrl)
    }

    private fun showWaiting() {
        val html = "<html dir='rtl'><body style='margin:0;height:100vh;display:flex;" +
            "align-items:center;justify-content:center;background:#0b0d14;color:#eef0f6;" +
            "font-family:sans-serif;text-align:center'><div style='padding:20px'>" +
            "<h2>VideoFPS Pro</h2>" +
            "<p>في انتظار السيرفر...</p>" +
            "<p style='color:#8b90a3;font-size:14px'>افتح Termux واكتب:<br>" +
            "<b>cd ~/inshot_src && python VideoFPS_Pro.py</b></p>" +
            "</div></body></html>"
        web.loadDataWithBaseURL(null, html, "text/html", "utf-8", null)
        handler.removeCallbacks(retry)
        handler.postDelayed(retry, retryMs)
    }

    override fun onDestroy() {
        handler.removeCallbacks(retry)
        super.onDestroy()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }
}
