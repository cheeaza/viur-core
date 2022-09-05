from collections import OrderedDict, namedtuple

import codecs
import logging
import os
import warnings
from jinja2 import ChoiceLoader, Environment, FileSystemLoader
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from viur.core import db, errors, securitykey, utils
from viur.core.bones import *
from viur.core.i18n import LanguageWrapper, TranslationExtension
from viur.core.skeleton import SkelList, SkeletonInstance
from viur.core.utils import currentLanguage, currentRequest
from . import utils as jinjaUtils

KeyValueWrapper = namedtuple("KeyValueWrapper", ["key", "descr"])


class Render(object):
    """
        The core jinja2 render.

        This is the bridge between your ViUR modules and your templates.
        First, the default jinja2-api is exposed to your templates. See http://jinja.pocoo.org/ for
        more information. Second, we'll pass data das global variables to templates depending on the
        current action.

            - For list() a `skellist` is provided containing all requested skeletons to a limit
            - For view(): skel - a dictionary with values from the skeleton prepared for use inside html
            - For add()/edit: a dictionary as `skel` with `values`, `structure` and `errors` as keys.

        Third, a bunch of global filters (like urlencode) and functions (getEntry, ..) are available  to templates.

        See the ViUR Documentation for more information about functions and data available to jinja2 templates.

        Its possible for modules to extend the list of filters/functions available to templates by defining
        a function called `jinjaEnv`. Its called from the render when the environment is first created and
        can extend/override the functionality exposed to templates.

    """
    kind = "html"

    listTemplate = "list"
    viewTemplate = "view"
    addTemplate = "add"
    editTemplate = "edit"

    addSuccessTemplate = "add_success"
    editSuccessTemplate = "edit_success"
    deleteSuccessTemplate = "delete_success"

    listRepositoriesTemplate = "list_repositories"
    reparentSuccessTemplate = "reparent_success"
    cloneSuccessTemplate = "clone_success"

    __haveEnvImported_ = False

    def __init__(self, parent=None, *args, **kwargs):
        super(Render, self).__init__(*args, **kwargs)
        if not Render.__haveEnvImported_:
            # We defer loading our plugins to this point to avoid circular imports
            # noinspection PyUnresolvedReferences
            from . import env
            Render.__haveEnvImported_ = True
        self.parent = parent

    def getTemplateFileName(self, template: str, ignoreStyle: bool = False) -> str:
        """
            Returns the filename of the template.

            This function decides in which language and which style a given template is rendered.
            The style is provided as get-parameters for special-case templates that differ from
            their usual way.

            It is advised to override this function in case that
            :func:`viur.core.render.jinja2.default.Render.getLoaders` is redefined.

            :param template: The basename of the template to use.
            :param ignoreStyle: Ignore any maybe given style hints.

            :returns: Filename of the template
        """
        validChars = "abcdefghijklmnopqrstuvwxyz1234567890-"
        if "htmlpath" in dir(self):
            htmlpath = self.htmlpath
        else:
            htmlpath = "html"
        currReq = currentRequest.get()
        if not ignoreStyle \
            and "style" in currReq.kwargs \
            and all([x in validChars for x in currReq.kwargs["style"].lower()]):
            stylePostfix = "_" + currReq.kwargs["style"]
        else:
            stylePostfix = ""
        lang = currentLanguage.get()  # session.current.getLanguage()
        fnames = [template + stylePostfix + ".html", template + ".html"]
        if lang:
            fnames = [os.path.join(lang, template + stylePostfix + ".html"),
                      template + stylePostfix + ".html",
                      os.path.join(lang, template + ".html"),
                      template + ".html"]
        for fn in fnames:  # check subfolders
            prefix = template.split("_")[0]
            if os.path.isfile(os.path.join(utils.projectBasePath, htmlpath, prefix, fn)):
                return "%s/%s" % (prefix, fn)
        for fn in fnames:  # Check the templatefolder of the application
            if os.path.isfile(os.path.join(utils.projectBasePath, htmlpath, fn)):
                return fn
        for fn in fnames:  # Check the fallback
            if os.path.isfile(os.path.join(utils.projectBasePath, "viur", "core", "template", fn)):
                return fn
        raise errors.NotFound("Template %s not found." % template)

    def getLoaders(self) -> ChoiceLoader:
        """
            Return the list of Jinja2 loaders which should be used.

            May be overridden to provide an alternative loader
            (e.g. for fetching templates from the datastore).
        """
        if "htmlpath" in dir(self):
            htmlpath = self.htmlpath
        else:
            htmlpath = "html/"

        return ChoiceLoader([FileSystemLoader(htmlpath), FileSystemLoader("viur/core/template/")])

    def renderBoneStructure(self, bone: baseBone) -> Dict[str, Any]:
        """
        Renders the structure of a bone.

        This function is used by :func:`renderSkelStructure`.
        can be overridden and super-called from a custom renderer.

        :param bone: The bone which structure should be rendered.
        :type bone: Any bone that inherits from :class:`server.bones.BaseBone`.

        :return: A dict containing the rendered attributes.
        """

        # Base bone contents.
        ret = {
            "descr": str(bone.descr),
            "type": bone.type,
            "required": bone.required,
            "multiple": bone.multiple,
            "params": bone.params,
            "visible": bone.visible,
            "readOnly": bone.readOnly
        }

        if bone.type == "relational" or bone.type.startswith("relational."):
            ret.update({
                "module": bone.module,
                "format": bone.format,
                "using": self.renderSkelStructure(bone.using()) if bone.using else None,
                "relskel": self.renderSkelStructure(bone._refSkelCache())
            })

        elif bone.type == "record" or bone.type.startswith("record."):
            ret.update({
                "format": bone.format,
                "using": self.renderSkelStructure(bone.using())
            })

        elif bone.type == "select" or bone.type.startswith("select."):
            ret.update({
                "values": {k: str(v) for (k, v) in bone.values.items()},
                "multiple": bone.multiple
            })

        elif bone.type == "date" or bone.type.startswith("date."):
            ret.update({
                "date": bone.date,
                "time": bone.time
            })

        elif bone.type == "numeric" or bone.type.startswith("numeric."):
            ret.update({
                "precision": bone.precision,
                "min": bone.min,
                "max": bone.max
            })

        elif bone.type == "text" or bone.type.startswith("text."):
            ret.update({
                "validHtml": bone.validHtml,
                "languages": bone.languages
            })

        elif bone.type == "str" or bone.type.startswith("str."):
            ret.update({
                "languages": bone.languages,
                "multiple": bone.multiple
            })
        elif bone.type == "captcha" or bone.type.startswith("captcha."):
            ret.update({
                "publicKey": bone.publicKey,
            })

        return ret

    def renderSkelStructure(self, skel: SkeletonInstance) -> Dict:
        """
            Dumps the structure of a :class:`viur.core.skeleton.Skeleton`.

            :param skel: Skeleton which structure will be processed.
            :returns: The rendered structure.
        """
        res = OrderedDict()

        for key, bone in skel.items():
            if "__" in key or not isinstance(bone, BaseBone):
                continue

            res[key] = self.renderBoneStructure(bone)

            if key in skel.errors:
                res[key]["error"] = skel.errors[key]
            else:
                res[key]["error"] = None

        return res

    def renderBoneValue(self,
                        bone: baseBone,
                        skel: SkeletonInstance,
                        key: Any,  # TODO: unused
                        boneValue: Any,
                        isLanguageWrapped: bool = False
                        ) -> Union[List, Dict, KeyValueWrapper, LanguageWrapper, str, None]:
        """
        Renders the value of a bone.

        It can be overridden and super-called from a custom renderer.

        :param bone: The bone which value should be rendered.
            (inherited from :class:`viur.core.bones.base.baseBone`).
        :param skel: The skeleton containing the bone instance.
        :param key: The name of the bone.
        :param boneValue: The value of the bone.
        :param isLanguageWrapped: Is this bone wrapped inside a :class:`LanguageWrapper`?

        :return: A dict containing the rendered attributes.
        """
        if bone.languages and not isLanguageWrapped:
            res = LanguageWrapper(bone.languages)
            if isinstance(boneValue, dict):
                for language in bone.languages:
                    if language in boneValue:
                        res[language] = self.renderBoneValue(bone, skel, key, boneValue[language], True)
            return res
        elif bone.type == "select" or bone.type.startswith("select."):
            skelValue = boneValue
            if isinstance(skelValue, list):
                return {
                    val: bone.values.get(val, val) for val in boneValue
                }
            elif skelValue in bone.values:
                return KeyValueWrapper(skelValue, bone.values[skelValue])
            return KeyValueWrapper(skelValue, str(skelValue))

        elif bone.type == "relational" or bone.type.startswith("relational."):
            if isinstance(boneValue, list):
                tmpList = []
                for k in boneValue:
                    if not k:
                        continue
                    if bone.using is not None and k["rel"]:
                        k["rel"].renderPreparation = self.renderBoneValue
                        usingData = k["rel"]
                    else:
                        usingData = None
                    k["dest"].renderPreparation = self.renderBoneValue
                    tmpList.append({
                        "dest": k["dest"],
                        "rel": usingData
                    })
                return tmpList
            elif isinstance(boneValue, dict):
                if bone.using is not None and boneValue["rel"]:
                    boneValue["rel"].renderPreparation = self.renderBoneValue
                    usingData = boneValue["rel"]
                else:
                    usingData = None
                boneValue["dest"].renderPreparation = self.renderBoneValue
                return {
                    "dest": boneValue["dest"],
                    "rel": usingData
                }
        elif bone.type == "record" or bone.type.startswith("record."):
            value = boneValue
            if value:
                if bone.multiple:
                    ret = []
                    for entry in value:
                        entry.renderPreparation = self.renderBoneValue
                        ret.append(entry)
                    return ret
                value.renderPreparation = self.renderBoneValue
                return value
        elif bone.type == "password":
            return ""
        elif bone.type == "key":
            return db.encodeKey(boneValue) if boneValue else None

        else:
            return boneValue

        return None

    def add(self, skel: SkeletonInstance, tpl: str = None, params: Any = None, *args, **kwargs) -> str:
        """
            Renders a page for adding an entry.

            The template must construct the HTML-form on itself; the required information
            are passed via skel.structure, skel.value and skel.errors.

            A jinja2-macro, which builds such kind of forms, is shipped with the server.

            Any data in \*\*kwargs is passed unmodified to the template.

            :param skel: Skeleton of the entry which should be created.
            :param tpl: Name of a different template, which should be used instead of the default one.
            :param params: Optional data that will be passed unmodified to the template

            :return: Returns the emitted HTML response.
        """
        if not tpl and "addTemplate" in dir(self.parent):
            tpl = self.parent.addTemplate

        tpl = tpl or self.addTemplate
        template = self.getEnv().get_template(self.getTemplateFileName(tpl))
        skeybone = BaseBone(descr="SecurityKey", readOnly=True, visible=False)
        skel.skey = skeybone
        skel["skey"] = securitykey.create()
        if currentRequest.get().kwargs.get("nomissing") == "1":
            if isinstance(skel, SkeletonInstance):
                super(SkeletonInstance, skel).__setattr__("errors", [])
        skel.renderPreparation = self.renderBoneValue
        return template.render(skel={"structure": self.renderSkelStructure(skel),
                                     "errors": skel.errors,
                                     "value": skel},
                               params=params, **kwargs)

    def edit(self, skel: SkeletonInstance, tpl: str = None, params: Any = None, **kwargs) -> str:
        """
            Renders a page for modifying an entry.

            The template must construct the HTML-form on itself; the required information
            are passed via skel.structure, skel.value and skel.errors.

            A jinja2-macro, which builds such kind of forms, is shipped with the server.

            Any data in \*\*kwargs is passed unmodified to the template.

            :param skel: Skeleton of the entry which should be modified.
            :param tpl: Name of a different template, which should be used instead of the default one.
            :param params: Optional data that will be passed unmodified to the template

            :return: Returns the emitted HTML response.
        """
        if not tpl and "editTemplate" in dir(self.parent):
            tpl = self.parent.editTemplate

        tpl = tpl or self.editTemplate
        template = self.getEnv().get_template(self.getTemplateFileName(tpl))
        skeybone = BaseBone(descr="SecurityKey", readOnly=True, visible=False)
        skel.skey = skeybone
        skel["skey"] = securitykey.create()

        if currentRequest.get().kwargs.get("nomissing") == "1":
            if isinstance(skel, SkeletonInstance):
                super(SkeletonInstance, skel).__setattr__("errors", [])
        skel.renderPreparation = self.renderBoneValue
        return template.render(skel={"structure": self.renderSkelStructure(skel),
                                     "errors": skel.errors,
                                     "value": skel},
                               params=params, **kwargs)

    def addSuccess(self, skel: SkeletonInstance, tpl: str = None, params: Any = None, *args, **kwargs) -> str:
        """
            Renders a page, informing that the entry has been successfully created.

            :param skel: Skeleton which contains the data of the new entity
            :param tpl: Name of a different template, which should be used instead of the default one.
            :param params: Optional data that will be passed unmodified to the template

            :return: Returns the emitted HTML response.
        """
        if not tpl:
            if "addSuccessTemplate" in dir(self.parent):
                tpl = self.parent.addSuccessTemplate
            else:
                tpl = self.addSuccessTemplate

        template = self.getEnv().get_template(self.getTemplateFileName(tpl))
        if isinstance(skel, SkeletonInstance):
            skel.renderPreparation = self.renderBoneValue
        return template.render({"skel": skel}, params=params, **kwargs)

    def editSuccess(self, skel: SkeletonInstance, tpl: str = None, params: Any = None, *args, **kwargs) -> str:
        """
            Renders a page, informing that the entry has been successfully modified.

            :param skel: Skeleton which contains the data of the modified entity
            :param tpl: Name of a different template, which should be used instead of the default one.
            :param params: Optional data that will be passed unmodified to the template

            :return: Returns the emitted HTML response.
        """
        if not tpl:
            if "editSuccessTemplate" in dir(self.parent):
                tpl = self.parent.editSuccessTemplate
            else:
                tpl = self.editSuccessTemplate

        template = self.getEnv().get_template(self.getTemplateFileName(tpl))
        if isinstance(skel, SkeletonInstance):
            skel.renderPreparation = self.renderBoneValue
        return template.render(skel=skel, params=params, **kwargs)

    def deleteSuccess(self, skel: SkeletonInstance, tpl: str = None, params: Any = None, *args, **kwargs) -> str:
        """
            Renders a page, informing that the entry has been successfully deleted.

            The provided parameters depend on the application calling this:
            List and Hierarchy pass the id of the deleted entry, while Tree passes
            the rootNode and path.

            :param skel: Skeleton which contains the data of the deleted entity
            :param params: Optional data that will be passed unmodified to the template
            :param tpl: Name of a different template, which should be used instead of the default one.

            :return: Returns the emitted HTML response.
        """
        if not tpl:
            if "deleteSuccessTemplate" in dir(self.parent):
                tpl = self.parent.deleteSuccessTemplate
            else:
                tpl = self.deleteSuccessTemplate

        template = self.getEnv().get_template(self.getTemplateFileName(tpl))
        return template.render(params=params, **kwargs)

    def list(self, skellist: SkelList, tpl: str = None, params: Any = None, **kwargs) -> str:
        """
            Renders a list of entries.

            Any data in \*\*kwargs is passed unmodified to the template.

            :param skellist: List of Skeletons with entries to display.
            :param tpl: Name of a different template, which should be used instead of the default one.
            :param params: Optional data that will be passed unmodified to the template

            :return: Returns the emitted HTML response.
        """
        if not tpl and "listTemplate" in dir(self.parent):
            tpl = self.parent.listTemplate
        tpl = tpl or self.listTemplate
        try:
            fn = self.getTemplateFileName(tpl)
        except errors.HTTPException as e:  # Not found - try default fallbacks
            tpl = "list"
        template = self.getEnv().get_template(self.getTemplateFileName(tpl))
        for skel in skellist:
            skel.renderPreparation = self.renderBoneValue
        return template.render(skellist=skellist, params=params, **kwargs)  # SkelListWrapper(resList, skellist)

    def listRootNodes(self,
                      repos: List[Dict[Literal["key", "name"], Any]],
                      tpl: str = None,
                      params: Any = None,
                      **kwargs
                      ) -> str:
        """
            Renders a list of available repositories.

            :param repos: List of repositories (dict with "key"=>Repo-Key and "name"=>Repo-Name)
            :param tpl: Name of a different template, which should be used instead of the default one.
            :param params: Optional data that will be passed unmodified to the template

            :return: Returns the emitted HTML response.
            :rtype: str
        """
        if "listRepositoriesTemplate" in dir(self.parent):
            tpl = tpl or self.parent.listTemplate
        if not tpl:
            tpl = self.listRepositoriesTemplate
        try:
            fn = self.getTemplateFileName(tpl)
        except errors.HTTPException as e:  # Not found - try default fallbacks
            tpl = "list"
        template = self.getEnv().get_template(self.getTemplateFileName(tpl))
        return template.render(repos=repos, params=params, **kwargs)

    def view(self, skel: SkeletonInstance, tpl: str = None, params: Any = None, **kwargs) -> str:
        """
            Renders a single entry.

            Any data in \*\*kwargs is passed unmodified to the template.

            :param skel: Skeleton to be displayed.
            :param tpl: Name of a different template, which should be used instead of the default one.
            :param params: Optional data that will be passed unmodified to the template

            :return: Returns the emitted HTML response.
        """
        if not tpl and "viewTemplate" in dir(self.parent):
            tpl = self.parent.viewTemplate

        tpl = tpl or self.viewTemplate
        template = self.getEnv().get_template(self.getTemplateFileName(tpl))

        if isinstance(skel, SkeletonInstance):
            skel.renderPreparation = self.renderBoneValue
        return template.render(skel=skel, params=params, **kwargs)

    ## Extended functionality for the Tree-Application ##

    def reparentSuccess(self, obj: SkeletonInstance, tpl: Optional[str] = None,
                        params: Any = None, **kwargs) -> str:
        """
            Renders a page informing that the item was successfully moved.

            :param obj: Skeleton instance of the item that was moved.
            :param tpl: Name of a different template, which should be used instead of the default one
            :param params: Optional data that will be passed unmodified to the template

            :return: Returns the emitted HTML response.
        """
        if not tpl:
            if "reparentSuccessTemplate" in dir(self.parent):
                tpl = self.parent.reparentSuccessTemplate
            else:
                tpl = self.reparentSuccessTemplate

        template = self.getEnv().get_template(self.getTemplateFileName(tpl))
        return template.render(repoObj=obj, params=params, **kwargs)

    def cloneSuccess(self, tpl: str = None, params: Any = None, *args, **kwargs) -> str:
        """
            Renders a page informing that the items sortindex was successfully changed.

            :param tpl: Name of a different template, which should be used instead of the default one
            :param params: Optional data that will be passed unmodified to the template

            :return: Returns the emitted HTML response.
        """
        if not tpl:
            if "cloneSuccessTemplate" in dir(self.parent):
                tpl = self.parent.cloneSuccessTemplate
            else:
                tpl = self.cloneSuccessTemplate

        template = self.getEnv().get_template(self.getTemplateFileName(tpl))
        return template.render(params=params, **kwargs)

    def renderEmail(self,
                    dests: List[str],
                    file: str = None,
                    template: str = None,
                    skel: Union[None, Dict, SkeletonInstance, List[SkeletonInstance]] = None,
                    **kwargs) -> Tuple[str, str]:
        """
            Renders an email.
            Uses the first not-empty line as subject and the remaining template as body.

            :param dests: Destination recipients.
            :param file: The name of a template from the deploy/emails directory.
            :param template: This string is interpreted as the template contents. Alternative to load from template file.
            :param skel: Skeleton or dict which data to supply to the template.
            :return: Returns the rendered email subject and body.
        """
        if isinstance(skel, SkeletonInstance):
            skel.renderPreparation = self.renderBoneValue
        elif isinstance(skel, list) and all([isinstance(x, SkeletonInstance) for x in skel]):
            for x in skel:
                x.renderPreparation = self.renderBoneValue
        if file is not None:
            try:
                tpl = self.getEnv().from_string(codecs.open("emails/" + file + ".email", "r", "utf-8").read())
            except Exception as err:
                logging.exception(err)
                tpl = self.getEnv().get_template(file + ".email")
        else:
            tpl = self.getEnv().from_string(template)
        content = tpl.render(skel=skel, dests=dests, **kwargs).lstrip().splitlines()
        if len(content) == 1:
            content.insert(0, "")  # add empty subject
        return content[0], os.linesep.join(content[1:]).lstrip()

    def getEnv(self) -> Environment:
        """
            Constucts the Jinja2 environment.

            If an application specifies an jinja2Env function, this function
            can alter the environment before its used to parse any template.

            :return: Extended Jinja2 environment.
        """

        def mkLambda(func, s):
            return lambda *args, **kwargs: func(s, *args, **kwargs)

        if not "env" in dir(self):
            loaders = self.getLoaders()
            self.env = Environment(loader=loaders,
                                   extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols", TranslationExtension])
            self.env.trCache = {}

            # Import functions.
            for name, func in jinjaUtils.getGlobalFunctions().items():
                self.env.globals[name] = mkLambda(func, self)

            # Import filters.
            for name, func in jinjaUtils.getGlobalFilters().items():
                self.env.filters[name] = mkLambda(func, self)

            # Import extensions.
            for ext in jinjaUtils.getGlobalExtensions():
                self.env.add_extension(ext)

            # Import module-specific environment, if available.
            if "jinjaEnv" in dir(self.parent):
                self.env = self.parent.jinjaEnv(self.env)

        return self.env
