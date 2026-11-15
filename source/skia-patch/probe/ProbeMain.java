package com.tv.skiaprobe;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.FileReader;
import java.util.Arrays;

/**
 * A/B probe for the libskia.so WebP alpha patch.
 *
 * Runs under `app_process` (a NON-zygote process), so LD_LIBRARY_PATH can
 * make the dynamic linker load a replacement libskia.so. A normal Activity
 * is forked from zygote and would inherit the already-mapped /system/lib
 * copy, which is why this cannot be done with an APK.
 *
 * Usage:
 *   app_process /system/bin com.tv.skiaprobe.ProbeMain <label>
 *
 * Writes /sdcard/Download/skiaprobe/<label>.txt and exported PNGs.
 */
public class ProbeMain {
    static final String DIR = "/sdcard/Download/webptest";
    static final String OUT = "/sdcard/Download/skiaprobe";
    static final StringBuilder report = new StringBuilder();

    static void log(String s) {
        report.append(s).append('\n');
        System.out.println(s);
    }

    /** Which libskia.so did the linker actually map into THIS process? */
    static String loadedSkia() {
        try {
            BufferedReader r = new BufferedReader(new FileReader("/proc/self/maps"));
            String line;
            while ((line = r.readLine()) != null) {
                if (line.contains("libskia.so")) {
                    r.close();
                    return line.trim();
                }
            }
            r.close();
        } catch (Throwable t) {
            return "ERR " + t;
        }
        return "NOT FOUND";
    }

    static void probe(File f, String label) {
        Bitmap bm = null;
        try {
            BitmapFactory.Options opt = new BitmapFactory.Options();
            opt.inPreferredConfig = Bitmap.Config.ARGB_8888;
            bm = BitmapFactory.decodeFile(f.getAbsolutePath(), opt);
            if (bm == null) {
                log("SAMPLE " + f.getName() + " => NULL");
                return;
            }
            int w = bm.getWidth(), h = bm.getHeight();
            int[] px = new int[w * h];
            bm.getPixels(px, 0, w, 0, 0, w, h);
            long sum = 0, alphaSum = 0;
            int opaque = 0, semi = 0, transparent = 0;
            for (int p : px) {
                sum = sum * 31 + (p & 0xffffffffL);
                int a = p >>> 24;
                alphaSum += a;
                if (a == 255) opaque++;
                else if (a == 0) transparent++;
                else semi++;
            }
            log("SAMPLE " + f.getName()
                    + " | " + w + "x" + h
                    + " | cfg=" + bm.getConfig()
                    + " | hasAlpha=" + bm.hasAlpha()
                    + " | checksum=" + Long.toHexString(sum)
                    + " | alphaSum=" + alphaSum
                    + " | opaque=" + opaque
                    + " | semi=" + semi
                    + " | transparent=" + transparent
                    + " | p0=" + Integer.toHexString(px[0])
                    + " | pc=" + Integer.toHexString(px[(h / 2) * w + w / 2])
                    + " | pEnd=" + Integer.toHexString(px[px.length - 1]));
            File o = new File(OUT, label + "_" + f.getName().replace('.', '_') + ".png");
            FileOutputStream fo = new FileOutputStream(o);
            bm.compress(Bitmap.CompressFormat.PNG, 100, fo);
            fo.flush();
            fo.close();
        } catch (Throwable t) {
            log("SAMPLE " + f.getName() + " EX " + t);
        } finally {
            if (bm != null) bm.recycle();
        }
    }

    public static void main(String[] args) {
        String label = (args != null && args.length > 0) ? args[0] : "run";
        new File(OUT).mkdirs();
        log("=== Skia A/B probe: " + label + " ===");
        log("PID=" + android.os.Process.myPid());
        log("LD_LIBRARY_PATH=" + System.getenv("LD_LIBRARY_PATH"));
        log("LIBSKIA_MAPS=" + loadedSkia());
        File[] fs = new File(DIR).listFiles();
        log("SAMPLE_COUNT=" + (fs == null ? -1 : fs.length));
        if (fs != null) {
            Arrays.sort(fs);
            for (File f : fs) {
                if (f.getName().endsWith(".webp") || f.getName().endsWith(".png")) {
                    probe(f, label);
                }
            }
        }
        log("=== DONE " + label + " ===");
        try {
            FileOutputStream fo = new FileOutputStream(new File(OUT, label + ".txt"));
            fo.write(report.toString().getBytes("UTF-8"));
            fo.flush();
            fo.close();
        } catch (Throwable t) {
            System.out.println("WRITE REPORT FAILED " + t);
        }
    }
}
