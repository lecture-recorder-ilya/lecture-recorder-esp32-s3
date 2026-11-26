package ru.ilya.lecturerecorder.test;

import android.app.Activity;
import android.app.Instrumentation;
import android.graphics.Rect;
import android.os.Bundle;
import android.util.Base64;
import android.util.Xml;
import android.view.accessibility.AccessibilityNodeInfo;
import java.io.StringWriter;
import java.nio.charset.StandardCharsets;
import org.xmlpull.v1.XmlSerializer;

public final class LiveSnapshot extends Instrumentation {
    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        start();
    }

    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            AccessibilityNodeInfo root = getUiAutomation().getRootInActiveWindow();
            if (root == null) throw new IllegalStateException("У окна нет доступного дерева");
            StringWriter buffer = new StringWriter();
            XmlSerializer xml = Xml.newSerializer();
            xml.setOutput(buffer);
            writeNode(xml, root);
            xml.flush();
            byte[] tree = buffer.toString().getBytes(StandardCharsets.UTF_8);
            result.putString("tree", Base64.encodeToString(tree, Base64.NO_WRAP));
            finish(Activity.RESULT_OK, result);
        } catch (Exception error) {
            result.putString("error", error.toString());
            finish(Activity.RESULT_CANCELED, result);
        }
    }

    private static void writeNode(XmlSerializer xml, AccessibilityNodeInfo node) throws Exception {
        Rect bounds = new Rect();
        node.getBoundsInScreen(bounds);
        xml.startTag(null, "node");
        attribute(xml, "text", node.getText());
        attribute(xml, "content-desc", node.getContentDescription());
        attribute(xml, "class", node.getClassName());
        attribute(xml, "bounds", bounds.toShortString());
        attribute(xml, "enabled", Boolean.toString(node.isEnabled()));
        attribute(xml, "clickable", Boolean.toString(node.isClickable()));
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null && child.isVisibleToUser()) writeNode(xml, child);
        }
        xml.endTag(null, "node");
    }

    private static void attribute(XmlSerializer xml, String key, CharSequence value) throws Exception {
        xml.attribute(null, key, value == null ? "" : value.toString());
    }
}
