package com.videofps.pro

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.webkit.*

class MainActivity : Activity() {
    private val url = "http://127.0.0.1:5000/"
    private val perm = "com.termux.permission.RUN_COMMAND"
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var web: WebView
    private val retry = Runnable { web.loadUrl(url) }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        web = WebView(this)
        web.setBackgroundColor(Color.parseColor("#0b0d14"))
        setContentView(web)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.webViewClient = object : WebViewClient() {
            override fun onReceivedError(v: WebView, r: WebResourceRequest, e: WebResourceError) {
                if (r.isForMainFrame) showWaiting()
            }
        }
        web.setDownloadListener { u, _, _, _, _ -> startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(u))) }
        if (checkSelfPermission(perm) == PackageManager.PERMISSION_GRANTED) startServer()
        else requestPermissions(arrayOf(perm), 1)
        web.loadUrl(url)
    }

    override fun onRequestPermissionsResult(c: Int, p: Array<out String>, r: IntArray) {
        super.onRequestPermissionsResult(c, p, r)
        if (c == 1 && r.isNotEmpty() && r[0] == PackageManager.PERMISSION_GRANTED) startServer()
    }

    private fun startServer() {
        val i = Intent().apply {
            setClassName("com.termux", "com.termux.app.RunCommandService")
            action = "com.termux.RUN_COMMAND"
            putExtra("com.termux.RUN_COMMAND_PATH", "/data/data/com.termux/files/usr/bin/python")
            putExtra("com.termux.RUN_COMMAND_ARGUMENTS", arrayOf("VideoFPS_Pro.py"))
            putExtra("com.termux.RUN_COMMAND_WORKDIR", "/data/data/com.termux/files/home/vfps2/VideoFPS_Android")
            putExtra("com.termux.RUN_COMMAND_BACKGROUND", true)
        }
        startService(i)
    }

    private fun showWaiting() {
        val html = "<html dir='rtl'><body style='margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#0b0d14;color:#eef0f6;font-family:sans-serif;text-align:center'><div><h2>VideoFPS Pro</h2><p>جاري تشغيل السيرفر...</p></div></body></html>"
        web.loadDataWithBaseURL(null, html, "text/html", "utf-8", null)
        handler.removeCallbacks(retry)
        handler.postDelayed(retry, 2000L)
    }

    override fun onDestroy() {
        handler.removeCallbacks(retry)
        super.onDestroy()
    }
}
