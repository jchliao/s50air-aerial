package com.tvhelper.root;

import android.app.Service;
import android.content.Intent;
import android.os.IBinder;

/**
 * 以 uid 1000 执行 /sdcard/Download/root.sh。
 *
 * 关键点：本包在 manifest 里声明 android:sharedUserId="android.uid.system"，
 * 并用电视的平台密钥签名。这样进程就是 android.uid.system（uid 1000），
 * Runtime.exec() 派生的 sh 继承 uid 1000，于是 pm / settings / am 都拿到
 * INSTALL_PACKAGES、CHANGE_COMPONENT_ENABLED_STATE 等系统权限。
 *
 * 直接 implements Runnable 是有意的：不产生匿名内部类，dex 里只有 1 个 class，
 * 在老 Dalvik 上不会因为 Shell$1 找不到而 NoClassDefFoundError。
 *
 * 为什么用 /system/bin/sh -c 包一层，而不是直接 exec("sh", "root.sh")：
 *   -c 让重定向（>> $LOG 2>&1）由 shell 自己解释，Java 侧不用建管道读输出；
 *   同时保证 === rc=$? === 拿到的是脚本本身的退出码。
 */
public class Shell extends Service implements Runnable {

    private volatile boolean busy = false;

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        spawn();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        spawn();
        return START_NOT_STICKY;
    }

    /** 防重入：上一次还没跑完时，再次触发直接忽略 */
    private void spawn() {
        if (busy) {
            return;
        }
        busy = true;
        Thread t = new Thread(this, "tvhelper");
        t.setDaemon(true);
        t.start();
    }

    @Override
    public void run() {
        String cmd =
                "LOG=/sdcard/Download/root.log; " +
                "echo \"=== start ===\" > $LOG 2>&1; " +
                "echo \"uid: $(id)\" >> $LOG 2>&1; " +
                "if [ -f /sdcard/Download/root.sh ]; then " +
                "  /system/bin/sh /sdcard/Download/root.sh >> $LOG 2>&1; " +
                "  echo \"=== rc=$? ===\" >> $LOG 2>&1; " +
                "else " +
                "  echo \"root.sh not found\" >> $LOG 2>&1; " +
                "fi; " +
                "echo \"=== done ===\" >> $LOG 2>&1";
        try {
            Process p = Runtime.getRuntime().exec(new String[]{"/system/bin/sh", "-c", cmd});
            p.waitFor();
        } catch (Throwable t) {
            try {
                Runtime.getRuntime().exec(new String[]{"/system/bin/sh", "-c",
                        "echo 'exec failure: " + String.valueOf(t).replace("'", " ") +
                                "' > /sdcard/Download/root.log"}).waitFor();
            } catch (Throwable ignored) {
            }
        }
        busy = false;
    }
}
