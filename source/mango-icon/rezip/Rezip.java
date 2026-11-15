import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;
public class Rezip {
  // Rebuild an APK preserving every entry (incl. v1 signature files) but
  // replacing classes4.dex. Java ZipFile reads via the central directory and
  // tolerates the empty local-header filenames produced by zipalign.
  public static void main(String[] a) throws Exception {
    String src=a[0], dexPath=a[1], dst=a[2];
    byte[] newDex=Files.readAllBytes(Paths.get(dexPath));
    try (ZipFile zf=new ZipFile(src);
         ZipOutputStream zos=new ZipOutputStream(new BufferedOutputStream(new FileOutputStream(dst)))) {
      Enumeration<? extends ZipEntry> en=zf.entries();
      int n=0;
      while (en.hasMoreElements()) {
        ZipEntry e=en.nextElement();
        ZipEntry ne=new ZipEntry(e.getName());
        ne.setTime(e.getTime());
        if (e.getComment()!=null) ne.setComment(e.getComment());
        ne.setMethod(ZipEntry.DEFLATED);
        zos.putNextEntry(ne);
        if (e.getName().equals("classes4.dex")) zos.write(newDex);
        else {
          try (InputStream is=zf.getInputStream(e)) {
            byte[] buf=new byte[65536]; int r;
            while ((r=is.read(buf))>0) zos.write(buf,0,r);
          }
        }
        zos.closeEntry(); n++;
      }
      System.out.println("entries="+n+" dex="+newDex.length+" dst="+dst);
    }
  }
}
