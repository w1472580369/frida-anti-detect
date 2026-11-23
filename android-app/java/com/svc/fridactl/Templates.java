package com.svc.fridactl;

import android.content.Context;
import android.content.res.AssetManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/**
 * 脚本模板库，内容来自 assets/templates.json。
 */
public final class Templates {

    private static JSONArray cache;

    private Templates() {
    }

    public static synchronized JSONArray all(Context context) {
        if (cache != null) {
            return cache;
        }
        try {
            AssetManager am = context.getAssets();
            try (InputStream is = am.open("templates.json")) {
                ByteArrayOutputStream bos = new ByteArrayOutputStream();
                byte[] buf = new byte[4096];
                int n;
                while ((n = is.read(buf)) > 0) {
                    bos.write(buf, 0, n);
                }
                cache = new JSONArray(new String(bos.toByteArray(), StandardCharsets.UTF_8));
            }
        } catch (Exception e) {
            LogBus.add("templates", "加载失败: " + e);
            cache = new JSONArray();
        }
        return cache;
    }

    public static JSONObject find(Context context, String name) {
        JSONArray arr = all(context);
        for (int i = 0; i < arr.length(); i++) {
            JSONObject o = arr.optJSONObject(i);
            if (o != null && name.equals(o.optString("name"))) {
                return o;
            }
        }
        return null;
    }
}
