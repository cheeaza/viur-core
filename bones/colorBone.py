# -*- coding: utf-8 -*-
from server.bones import baseBone
import logging

class colorBone( baseBone ):
	type = "color"

	def __init__(self,  mode="rgb",   *args,  **kwargs ): #mode rgb/rgba
		baseBone.__init__( self,  *args,  **kwargs )
		assert mode in ["rgb", "rgba"]
		self.mode = mode

	def fromClient( self, name, data ):
		"""
			Reads a value from the client.
			If this value is valis for this bone,
			store this value and return None.
			Otherwise our previous value is
			left unchanged and an error-message
			is returned.
			
			@param name: Our name in the skeleton
			@type name: String
			@param data: *User-supplied* request-data
			@type data: Dict
			@returns: None or String
		"""
		if name in data.keys():
			value = data[ name ]
		else:
			value = None
		if self.mode!="rgb" and self.mode!="rgba":
			return( "Invalid mode selected" )
		if value==None:
			return (None)
		value=value.lower()
		if value.count("#")>1:
			return( "Invalid value entered" )
		for char in value:
			if not char in "#0123456789abcdef":
				return( "Invalid value entered" )
		if self.mode=="rgb":
			if len(value)==3:
				value="#"+value
			if len(value)==4:
				value=value[0:2]+value[1]+2*value[2]+2*value[3]
			if len(value)==6 or len(value)==7:
				if len (value)==6:
					value="#"+value
				self.value=value
				return (None)
			else:
				return( "Invalid value entered" )
		if self.mode=="rgba":
			if len(value)==8 or len(value)==9:
				if len (value)==8:
					value="#"+value
				self.value=value
				return (None)
			else:
				return( "Invalid value entered" )
		return (None)