package com.tv.memprobe;
import android.app.ActivityManager;
import java.lang.reflect.Method;
public class MemProbe {
  public static void main(String[] args) {
    try {
      Class<?> p = Class.forName("android.os.Process");
      Object free = p.getMethod("getFreeMemory").invoke(null);
      Object total = p.getMethod("getTotalMemory").invoke(null);
      System.out.println("MEMPROBE getFreeMemory=" + free + " getTotalMemory=" + total);
      Class<?> c = Class.forName("android.app.ActivityManagerNative");
      Object am = c.getMethod("getDefault").invoke(null);
      ActivityManager.MemoryInfo mi = new ActivityManager.MemoryInfo();
      Method m = Class.forName("android.app.IActivityManager")
                     .getMethod("getMemoryInfo", ActivityManager.MemoryInfo.class);
      m.invoke(am, mi);
      System.out.println("MEMPROBE lowMemory=" + mi.lowMemory
          + " availMem=" + mi.availMem
          + " threshold=" + mi.threshold
          + " totalMem=" + mi.totalMem);
    } catch (Throwable t) {
      System.out.println("MEMPROBE FAIL " + t);
      t.printStackTrace();
    }
  }
}
