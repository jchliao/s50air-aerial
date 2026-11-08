package com.tv.sourceshortcut;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

public class MainActivity extends Activity {

    /** 显示名 → extraPort 值（与 SSM SourceBase.doSwitchPort 认的字符串一致） */
    static final String[][] PORTS = {
        {"HDMI 1",   "HDMI 1"},
        {"HDMI 2",   "HDMI 2"},
        {"HDMI 3",   "HDMI 3"},
        {"Super TV", "Super TV"},
    };

    static final String SSM_PKG = "com.stv.signalsourcemanager";
    static final String SSM_CLS = "com.stv.signalsourcemanager.MainActivity";
    static final String ACTION_INSTALL_SHORTCUT = "com.android.launcher.action.INSTALL_SHORTCUT";

    EditText nameEdit;
    RadioGroup portsGroup;

    int dp(int v) {
        return (int) (v * getResources().getDisplayMetrics().density);
    }

    String portValue() {
        int id = portsGroup.getCheckedRadioButtonId();
        for (int i = 0; i < PORTS.length; i++) {
            if (id == 1000 + i) return PORTS[i][1];
        }
        return PORTS[0][1];
    }

    String portLabel() {
        int id = portsGroup.getCheckedRadioButtonId();
        for (int i = 0; i < PORTS.length; i++) {
            if (id == 1000 + i) return PORTS[i][0];
        }
        return PORTS[0][0];
    }

    /** 构造点击快捷方式后的切源 Intent */
    Intent buildTarget() {
        Intent t = new Intent();
        t.setClassName(SSM_PKG, SSM_CLS);
        t.putExtra("extraPort", portValue());
        t.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        return t;
    }

    TextView makeLabel(String text) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextSize(15);
        tv.setPadding(0, dp(10), 0, dp(4));
        return tv;
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // 横屏 TV 布局: ScrollView 防裁切；内容宽度取屏宽一半，自适应不同 density
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);

        android.util.DisplayMetrics dm = new android.util.DisplayMetrics();
        getWindowManager().getDefaultDisplay().getMetrics(dm);
        int contentW = dm.widthPixels / 2;
        int btnW = contentW / 2 - dp(12);
        int btnH = dp(52);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        int pad = dp(24);
        root.setPadding(pad, pad, pad, pad);
        scroll.addView(root);

        TextView title = new TextView(this);
        title.setText("信号源快捷方式");
        title.setTextSize(20);
        title.setGravity(Gravity.CENTER);
        title.setPadding(0, 0, 0, dp(12));
        root.addView(title, new LinearLayout.LayoutParams(contentW,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        root.addView(makeLabel("名称："));
        nameEdit = new EditText(this);
        nameEdit.setText("PS4");
        nameEdit.setTextSize(16);
        nameEdit.setSingleLine();
        root.addView(nameEdit, new LinearLayout.LayoutParams(contentW,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        root.addView(makeLabel("信号源："));
        portsGroup = new RadioGroup(this);
        portsGroup.setOrientation(LinearLayout.HORIZONTAL);
        for (int i = 0; i < PORTS.length; i++) {
            RadioButton rb = new RadioButton(this);
            rb.setId(1000 + i);
            rb.setText(PORTS[i][0]);
            rb.setTextSize(16);
            rb.setPadding(dp(6), dp(2), dp(16), dp(2));
            portsGroup.addView(rb);
        }
        portsGroup.check(1000);
        root.addView(portsGroup, new LinearLayout.LayoutParams(contentW,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        // Aerial 桌面不支持 INSTALL_SHORTCUT，先只保留直接切换
        Button test = new Button(this);
        test.setText("切换");
        test.setTextSize(16);
        test.setGravity(Gravity.CENTER);
        test.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                try {
                    startActivity(buildTarget());
                } catch (Exception e) {
                    Toast.makeText(MainActivity.this,
                            "启动失败: " + e.getMessage(), Toast.LENGTH_LONG).show();
                }
            }
        });

        LinearLayout btnRow = new LinearLayout(this);
        btnRow.setOrientation(LinearLayout.HORIZONTAL);
        btnRow.setGravity(Gravity.CENTER);
        btnRow.setPadding(0, dp(20), 0, dp(8));
        btnRow.addView(test, new LinearLayout.LayoutParams(btnW * 2, btnH));
        root.addView(btnRow, new LinearLayout.LayoutParams(contentW,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        setContentView(scroll);
    }
}
