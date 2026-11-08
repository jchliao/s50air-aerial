package PKGPLACEHOLDER;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

/** 直达信号源的桌面入口：启动即切源并退出（PS4 等命名交给 Aerial 手机页改名） */
public class JumpActivity extends Activity {
    static final String PORT = "PORTPLACEHOLDER";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        try {
            Intent t = new Intent();
            t.setClassName("com.stv.signalsourcemanager", "com.stv.signalsourcemanager.MainActivity");
            t.putExtra("extraPort", PORT);
            t.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(t);
        } catch (Exception ignored) {
        }
        finish();
    }
}
