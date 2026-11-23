(function webpackUniversalModuleDefinition(root, factory) {
	if(typeof exports === 'object' && typeof module === 'object')
		module.exports = factory();
	else if(typeof define === 'function' && define.amd)
		define([], factory);
	else {
		var a = factory();
		for(var i in a) (typeof exports === 'object' ? exports : root)[i] = a[i];
	}
})((typeof self !== 'undefined' ? self : this), function() {
return  (function() {
	"use strict";
var __webpack_exports__ = {};

;
const defaultCopyDelimiters = {
  inline: ['$', '$'],
  display: ['$$', '$$']
};

function katexReplaceWithTex(fragment, copyDelimiters) {
  if (copyDelimiters === void 0) {
    copyDelimiters = defaultCopyDelimiters;
  }
  const katexHtml = fragment.querySelectorAll('.katex-mathml + .katex-html');
  for (let i = 0; i < katexHtml.length; i++) {
    const element = katexHtml[i];
    if (element.remove) {
      element.remove();
    } else if (element.parentNode) {
      element.parentNode.removeChild(element);
    }
  }
  const katexMathml = fragment.querySelectorAll('.katex-mathml');
  for (let i = 0; i < katexMathml.length; i++) {
    const element = katexMathml[i];
    const texSource = element.querySelector('annotation');
    if (texSource) {
      if (element.replaceWith) {
        element.replaceWith(texSource);
      } else if (element.parentNode) {
        element.parentNode.replaceChild(texSource, element);
      }
      texSource.innerHTML = copyDelimiters.inline[0] + texSource.innerHTML + copyDelimiters.inline[1];
    }
  }
  const displays = fragment.querySelectorAll('.katex-display annotation');
  for (let i = 0; i < displays.length; i++) {
    const element = displays[i];
    element.innerHTML = copyDelimiters.display[0] + element.innerHTML.substr(copyDelimiters.inline[0].length, element.innerHTML.length - copyDelimiters.inline[0].length - copyDelimiters.inline[1].length) + copyDelimiters.display[1];
  }
  return fragment;
}
 var katex2tex = (katexReplaceWithTex);
;


function closestKatex(node) {
  const element = node instanceof Element ? node : node.parentElement;
  return element && element.closest('.katex');
}

document.addEventListener('copy', function (event) {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || !event.clipboardData) {
    return;
  }
  const clipboardData = event.clipboardData;
  const range = selection.getRangeAt(0);

  const startKatex = closestKatex(range.startContainer);
  if (startKatex) {
    range.setStartBefore(startKatex);
  }

  const endKatex = closestKatex(range.endContainer);
  if (endKatex) {
    range.setEndAfter(endKatex);
  }
  const fragment = range.cloneContents();
  if (!fragment.querySelector('.katex-mathml')) {
    return;
  }
  const htmlContents = Array.prototype.map.call(fragment.childNodes, el => el instanceof Text ? el.textContent : el.outerHTML).join('');

  clipboardData.setData('text/html', htmlContents);
  clipboardData.setData('text/plain', katex2tex(fragment).textContent);
  event.preventDefault();
});
__webpack_exports__ = __webpack_exports__["default"];
	return __webpack_exports__;
 })()
;
});